# -*- coding: utf-8 -*-
"""知识库索引：正文复制到 items/，元数据与分类存 index.json"""
import json
import os
import re
import shutil
import sys
import threading
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from app.renderer import MdRenderer, iter_local_images, read_text

UNTAGGED = None
ILLEGAL_FN = re.compile(r"[\\/:*?\"<>|]")
SCHEMA_VERSION = 2
ID_RE = re.compile(r"^[0-9a-f]{12}$")


def atomic_write(path: Path, data) -> None:
    """先写同目录临时文件再 os.replace，避免断电/崩溃留下半截文件"""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    if isinstance(data, bytes):
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    else:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    os.replace(tmp, path)


class KnowledgeIndex:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.items_dir = self.root / "items"
        self.items_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.root / "index.json"
        self.categories = []
        self.entries = []
        self._lock = threading.RLock()
        self._load()

    def _load(self):
        if not self.index_file.exists():
            return
        try:
            raw = json.loads(self.index_file.read_text(encoding="utf-8"))
        except Exception as ex:
            # 索引损坏：先留一份现场，再从 items/ 重建，别让一次坏文件把整个库变成空的
            try:
                bad = self.index_file.with_name(
                    "index.json.bad-%s" % datetime.now().strftime("%Y%m%d-%H%M%S"))
                shutil.copyfile(self.index_file, bad)
                print("索引无法解析(%s)，已备份为 %s" % (ex, bad.name), file=sys.stderr)
            except OSError:
                print("索引无法解析且备份失败: %s" % ex, file=sys.stderr)
            self._rebuild_from_items()
            return
        if isinstance(raw, list):          # v1: 只有条目列表，无分类
            self.entries = raw
        elif isinstance(raw, dict):
            self.categories = [c for c in raw.get("categories", []) if isinstance(c, dict)]
            self.entries = [e for e in raw.get("entries", []) if isinstance(e, dict)]
        for e in self.entries:
            if e.get("origin_dir"):
                e["origin_dir"] = str(Path(e["origin_dir"]).resolve())
        # 老库没有 version 字段，启动时顺手升级到当前 schema（只读库忽略失败）
        if not isinstance(raw, dict) or raw.get("version") != SCHEMA_VERSION:
            try:
                self._save()
            except OSError:
                pass

    def _rebuild_from_items(self):
        """按 items/ 里的正文重建条目：标题与标签重新解析，原件位置已无从得知"""
        rebuilt = []
        for f in sorted(self.items_dir.glob("*.md")):
            eid = f.stem
            if not ID_RE.match(eid):
                continue
            try:
                title, tags, _ = MdRenderer.parse_file(f)
            except Exception:
                title, tags = None, []
            try:
                stamp = datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds")
            except OSError:
                stamp = datetime.now().isoformat(timespec="seconds")
            rebuilt.append({
                "id": eid,
                "title": title or eid,
                "alias": None,
                "tags": [str(t) for t in tags] if isinstance(tags, list) else [],
                "source_name": (title or eid) + ".md",
                "origin_dir": None,
                "category": UNTAGGED,
                "added_at": stamp,
                "updated_at": stamp,
            })
        self.entries = rebuilt
        self.categories = []
        self._save()
        print("索引已从 items/ 重建：%d 条" % len(rebuilt), file=sys.stderr)

    def _save(self):
        payload = json.dumps(
            {"version": SCHEMA_VERSION, "categories": self.categories, "entries": self.entries},
            ensure_ascii=False, indent=2)
        with self._lock:
            atomic_write(self.index_file, payload)

    # ---------- 知识点 ----------
    def add(self, src, category=UNTAGGED) -> dict:
        src = Path(src).resolve()
        title, tags, body = MdRenderer.parse_file(src)
        existing = next(
            (e for e in self.entries
             if e.get("source_name") == src.name and e.get("origin_dir") == str(src.parent)),
            None,
        )
        eid = existing["id"] if existing else uuid.uuid4().hex[:12]
        # 统一转存为 UTF-8：源文件可能是 GBK/BOM，原样复制会让后面每次读取都解码失败
        atomic_write(self.items_dir / ("%s.md" % eid), read_text(src).encode("utf-8"))
        self.sync_assets(eid, body, src.parent)
        if category is UNTAGGED and existing:
            category = existing.get("category")
        entry = {
            "id": eid,
            "title": title or src.stem,
            "alias": (existing or {}).get("alias"),
            "tags": [str(t) for t in tags] if isinstance(tags, list) else [str(tags)] if tags else [],
            "source_name": src.name,
            "origin_dir": str(src.parent),
            "category": category if self.find_category(category) else UNTAGGED,
            "added_at": (existing or {}).get("added_at", datetime.now().isoformat(timespec="seconds")),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.entries = [entry if e["id"] == eid else e for e in self.entries]
        if not existing:
            self.entries.append(entry)
        self._save()
        return entry

    def create(self, title="未命名知识点", category=UNTAGGED, content=None) -> dict:
        """在库内直接新建一篇知识点：没有外部原件，正文就是 items/<id>.md"""
        title = str(title or "").strip()[:60] or "未命名知识点"
        eid = uuid.uuid4().hex[:12]
        if content is None:
            content = "# %s\n\n在这里开始写。\n" % title
        atomic_write(self.items_dir / ("%s.md" % eid), str(content).encode("utf-8"))
        now = datetime.now().isoformat(timespec="seconds")
        entry = {
            "id": eid,
            "title": title,
            "alias": None,
            "tags": [],
            "source_name": title + ".md",
            "origin_dir": None,              # 库内新建，没有外部原件
            "category": category if self.find_category(category) else UNTAGGED,
            "added_at": now,
            "updated_at": now,
        }
        self.entries.append(entry)
        self._save()
        return entry

    def remove(self, eid: str):
        self.entries = [e for e in self.entries if e["id"] != eid]
        f = self.items_dir / ("%s.md" % eid)
        if f.exists():
            f.unlink()
        # 图片是导入时复制的副本，原件仍在原目录，删副本不影响用户数据
        shutil.rmtree(self.assets_dir(eid), ignore_errors=True)
        self._save()

    # ---------- 图片副本：让 library/ 自包含 ----------
    def assets_dir(self, eid: str) -> Path:
        return self.root / "assets" / eid

    def sync_assets(self, eid: str, body: str, origin) -> None:
        """把正文引用的相对路径图片复制到 library/assets/<eid>/，并清掉不再引用的旧副本"""
        if not origin:
            return
        origin = Path(origin)
        if not origin.is_dir():
            return
        adir = self.assets_dir(eid)
        keep = set()
        for rel in iter_local_images(body):
            if not rel or rel.startswith("/"):
                continue
            try:
                src = (origin / rel).resolve()
                src.relative_to(origin.resolve())
            except (ValueError, OSError):
                continue                  # 穿出原件目录的引用不复制
            if not src.is_file():
                continue
            dst = adir / rel
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                sstat = src.stat()
                if not (dst.is_file() and dst.stat().st_size == sstat.st_size
                        and dst.stat().st_mtime >= sstat.st_mtime):
                    shutil.copyfile(src, dst)
                keep.add(dst.resolve())
            except OSError:
                continue
        if not adir.is_dir():
            return
        for f in adir.rglob("*"):
            if f.is_file() and f.resolve() not in keep:
                try:
                    f.unlink()
                except OSError:
                    pass
        for d in sorted((p for p in adir.rglob("*") if p.is_dir()),
                        key=lambda p: len(p.parts), reverse=True):
            try:
                d.rmdir()
            except OSError:
                pass

    def sync_all_assets(self):
        """启动时后台补齐老库的图片副本；单条失败不影响其他条目"""
        for e in list(self.entries):
            try:
                self.sync_assets(e["id"], read_text(self.path(e["id"])), e.get("origin_dir"))
            except Exception:
                continue

    def set_category(self, eid: str, category):
        category = category if self.find_category(category) else UNTAGGED
        for e in self.entries:
            if e["id"] == eid:
                e["category"] = category
        self._save()

    def set_alias(self, eid: str, alias) -> dict:
        """自定义显示名；传空串则恢复使用文件里的标题"""
        alias = str(alias or "").strip()[:60]
        entry = self.find(eid)
        entry["alias"] = alias or None
        entry["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._save()
        return entry

    def rename_source(self, eid: str, new_name: str) -> dict:
        """重命名磁盘上的 .md 原件（显示名与索引同步更新）"""
        entry = self.find(eid)
        if not entry.get("origin_dir"):
            raise ValueError("这篇是库内新建的知识点，没有外部文件需要重命名")
        name = str(new_name or "").strip()
        if not name:
            raise ValueError("文件名不能为空")
        if ILLEGAL_FN.search(name) or name.rstrip(".") != name or name in (".", ".."):
            raise ValueError('文件名不能包含 \\ / : * ? " < > |，也不能以点结尾')
        if not name.lower().endswith(".md"):
            name += ".md"
        origin = Path(entry.get("origin_dir") or "")
        old = origin / entry.get("source_name", "")
        if not origin.is_dir() or not old.is_file():
            raise ValueError("原文件已不在记录位置，无法重命名文件")
        target = origin / name
        if target.exists():
            raise ValueError("同级目录下已有同名文件：" + name)
        old.rename(target)
        entry["source_name"] = target.name
        entry["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._save()
        return entry

    @staticmethod
    def display(entry: dict) -> str:
        return entry.get("alias") or entry.get("title") or ""

    def path(self, eid: str) -> Path:
        return self.items_dir / ("%s.md" % eid)

    def source_path(self, eid: str) -> Path:
        """可编辑的原件位置：优先原始文件，找不到时退回库内副本"""
        entry = self.find(eid)
        origin = entry.get("origin_dir")
        if origin:
            p = Path(origin) / entry.get("source_name", "")
            if p.is_file():
                return p
        return self.path(eid)

    def save_source(self, eid: str, content: str) -> dict:
        """覆盖写入前把旧内容备份到 library/backups/，并同步库内副本与索引元数据"""
        target = self.source_path(eid)
        backup = None
        if target.is_file():
            bdir = self.root / "backups"
            bdir.mkdir(parents=True, exist_ok=True)
            backup = bdir / ("%s.%s.md" % (eid, datetime.now().strftime("%Y%m%d-%H%M%S")))
            shutil.copyfile(target, backup)
        atomic_write(target, content.encode("utf-8"))

        item = self.path(eid)
        if target != item:
            atomic_write(item, content.encode("utf-8"))

        title, tags, body = MdRenderer.parse_file(target)
        entry = self.find(eid)
        entry["title"] = title or entry["title"]
        entry["tags"] = tags
        entry["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self.sync_assets(eid, body, entry.get("origin_dir"))
        self._save()
        return {
            "path": str(target),
            "backup": str(backup) if backup else None,
            "title": entry["title"],
            "tags": entry["tags"],
        }

    def find(self, eid: str) -> dict:
        return next(e for e in self.entries if e["id"] == eid)

    # ---------- 分类 ----------
    def add_category(self, name: str) -> dict:
        name = str(name).strip()[:40]
        if not name:
            raise ValueError("分类名不能为空")
        hit = next((c for c in self.categories if c["name"] == name), None)
        if hit:
            return hit
        cat = {
            "id": uuid.uuid4().hex[:10],
            "name": name,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.categories.append(cat)
        self._save()
        return cat

    def rename_category(self, cid: str, name: str) -> dict:
        name = str(name).strip()[:40]
        if not name:
            raise ValueError("分类名不能为空")
        cat = self.find_category(cid)
        if not cat:
            raise KeyError(cid)
        cat["name"] = name
        self._save()
        return cat

    def delete_category(self, cid: str):
        """删除分类本身，其中的知识点退回未分类"""
        self.categories = [c for c in self.categories if c["id"] != cid]
        for e in self.entries:
            if e.get("category") == cid:
                e["category"] = UNTAGGED
        self._save()

    def find_category(self, cid):
        if not cid:
            return None
        return next((c for c in self.categories if c["id"] == cid), None)

    def category_view(self):
        counts = {}
        for e in self.entries:
            key = e.get("category") or UNTAGGED
            counts[key] = counts.get(key, 0) + 1
        out = [{"id": c["id"], "name": c["name"], "count": counts.get(c["id"], 0)}
               for c in self.categories]
        return out, counts.get(UNTAGGED, 0)

    # ---------- 导出 ----------
    def export_entry(self, eid: str, dest_dir) -> dict:
        """把一条知识点连同图片按原相对路径导出成一个独立文件夹，正文用相对路径引用仍然有效"""
        entry = self.find(eid)
        name = ILLEGAL_FN.sub("_", KnowledgeIndex.display(entry)).strip(" .") or eid
        target = Path(dest_dir) / name
        target.mkdir(parents=True, exist_ok=True)

        body = read_text(self.path(eid))
        atomic_write(target / ("%s.md" % name), body.encode("utf-8"))

        images = 0
        adir = self.assets_dir(eid)
        if adir.is_dir():
            for f in adir.rglob("*"):
                if not f.is_file():
                    continue
                dst = target / f.relative_to(adir)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(f, dst)
                images += 1
        return {"path": str(target), "images": images}

    def export_library(self, dest_dir) -> dict:
        """整个库打成一个 zip，含索引、正文、图片副本与设置，可直接搬迁恢复"""
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        out = dest / ("知览备份-%s.zip" % datetime.now().strftime("%Y%m%d-%H%M%S"))
        count = 0
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(self.root.rglob("*")):
                if f.is_file() and not f.name.endswith(".tmp"):
                    z.write(f, f.relative_to(self.root))
                    count += 1
        return {"path": str(out), "files": count, "bytes": out.stat().st_size}

    # ---------- 存储维护 ----------
    def _orphan_files(self):
        """已不属于任何条目的备份、正文副本与图片副本（现存条目的历史备份一律保留）"""
        ids = {e["id"] for e in self.entries}
        out = []
        bdir = self.root / "backups"
        if bdir.is_dir():
            out += [f for f in bdir.iterdir()
                    if f.is_file() and f.name.split(".")[0] not in ids]
        if self.items_dir.is_dir():
            out += [f for f in self.items_dir.glob("*.md") if f.stem not in ids]
        adir = self.root / "assets"
        if adir.is_dir():
            for d in adir.iterdir():
                if d.is_dir() and d.name not in ids:
                    out += [f for f in d.rglob("*") if f.is_file()]
        return out

    def orphan_report(self) -> dict:
        files = self._orphan_files()
        total = 0
        for f in files:
            try:
                total += f.stat().st_size
            except OSError:
                pass
        return {"files": len(files), "bytes": total}

    def cleanup(self) -> dict:
        removed, freed = 0, 0
        for f in self._orphan_files():
            try:
                freed += f.stat().st_size
                f.unlink()
                removed += 1
            except OSError:
                pass
        adir = self.root / "assets"
        if adir.is_dir():
            for d in adir.iterdir():
                if d.is_dir() and not any(d.iterdir()):
                    shutil.rmtree(d, ignore_errors=True)
        return {"removed": removed, "freed": freed}
