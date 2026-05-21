from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import jieba
from sqlalchemy import text

from database import get_session, engine
from database.models import MemorySegment


def _safe_parse_datetime(value):
    """安全地解析日期时间，支持字符串和日期对象"""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            # 尝试解析 ISO 格式
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                # 尝试其他常见格式
                return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None
    return None


@dataclass
class MemorySegmentData:
    segment_id: str
    memory_type: str
    related_id: str | None
    content: str
    metadata: dict[str, Any] | None
    created_at: datetime | None
    score: float = 0.0

    @classmethod
    def from_orm(cls, row: MemorySegment, score: float = 0.0) -> MemorySegmentData:
        return cls(
            segment_id=str(row.segment_id),
            memory_type=str(row.memory_type),
            related_id=str(row.related_id) if row.related_id else None,
            content=str(row.content) if row.content else "",
            metadata=dict(row.meta_data) if row.meta_data else None,
            created_at=row.created_at,
            score=score,
        )


class MemorySearcher:
    LONG_TERM = "long_term"
    SKILL = "skill"

    def __init__(self, default_limit: int = 5, min_score: float = 0.0):
        self.default_limit = default_limit
        self.min_score = min_score

    def _tokenize_text(self, text: str) -> str:
        """使用 jieba 分词，返回空格分隔的字符串"""
        if not text:
            return ""
        
        words = jieba.cut_for_search(text)  # 搜索引擎模式，分词更细
        token_list = [w.strip() for w in words if w.strip() and len(w.strip()) > 0]
        
        # 去重，避免重复分词影响结果
        unique_tokens = list(set(token_list))
        
        return " ".join(unique_tokens)

    def search(
        self,
        query: str,
        memory_type: str | None = None,
        related_id: str | None = None,
        limit: int | None = None,
    ) -> list[MemorySegmentData]:
        if not query or not query.strip():
            return []

        search_limit = limit if limit is not None else self.default_limit
        
        # 对查询进行 jieba 分词
        tokenized_query = self._tokenize_text(query)
        
        if not tokenized_query:
            return []
        
        with engine.connect() as conn:
            sql_parts = [
                "SELECT ms.segment_id, ms.memory_type, ms.related_id, ms.content, ms.meta_data, ms.created_at,",
                "       bm25(memory_segments_fts) AS score",
                "FROM memory_segments ms",
                "JOIN memory_segments_fts fts ON ms.segment_id = fts.segment_id",
                "WHERE memory_segments_fts MATCH :query",
            ]
            params = {"query": tokenized_query}

            if memory_type:
                sql_parts.append("AND ms.memory_type = :memory_type")
                params["memory_type"] = memory_type

            if related_id:
                sql_parts.append("AND ms.related_id = :related_id")
                params["related_id"] = related_id

            sql_parts.append("ORDER BY score ASC")
            sql_parts.append("LIMIT :limit")
            params["limit"] = search_limit

            sql = text(" ".join(sql_parts))
            result = conn.execute(sql, params)

            segments = []
            for row in result:
                score = float(row.score) if row.score else 0.0
                meta = None
                if row.meta_data:
                    try:
                        if isinstance(row.meta_data, str):
                            import json
                            meta = json.loads(row.meta_data)
                        elif isinstance(row.meta_data, dict):
                            meta = row.meta_data
                    except Exception:
                        pass
                
                segments.append(
                    MemorySegmentData(
                        segment_id=str(row.segment_id),
                        memory_type=str(row.memory_type),
                        related_id=str(row.related_id) if row.related_id else None,
                        content=str(row.content) if row.content else "",
                        metadata=meta,
                        created_at=_safe_parse_datetime(row.created_at),
                        score=abs(score),
                    )
                )
            
            # 如果 FTS 查不到结果，回退到 LIKE 查询
            if not segments:
                segments = self._fallback_like_search(
                    conn, query, memory_type, related_id, search_limit
                )
            
            return segments

    def _fallback_like_search(
        self,
        conn,
        query: str,
        memory_type: str | None,
        related_id: str | None,
        limit: int,
    ) -> list[MemorySegmentData]:
        import json
        
        # 使用 jieba 进行中文分词
        words = jieba.cut_for_search(query)
        keywords = [w.strip() for w in words if w.strip() and len(w.strip()) > 0]
        
        if len(keywords) == 0:
            return []
        
        # 构建 OR 条件的 LIKE 查询（使用命名参数）
        param_dict = {}
        like_parts = []
        for i, keyword in enumerate(keywords):
            param_name = f"kw{i}"
            like_parts.append(f"content LIKE :{param_name}")
            param_dict[param_name] = f"%{keyword}%"
        
        like_conditions = " OR ".join(like_parts)
        
        sql_parts = [
            "SELECT segment_id, memory_type, related_id, content, meta_data, created_at, 1.0 AS score",
            "FROM memory_segments",
            f"WHERE ({like_conditions})",
        ]
        
        if memory_type:
            sql_parts.append("AND memory_type = :memory_type")
            param_dict["memory_type"] = memory_type
        
        if related_id:
            sql_parts.append("AND related_id = :related_id")
            param_dict["related_id"] = related_id
        
        sql_parts.append("ORDER BY created_at DESC")
        sql_parts.append("LIMIT :limit")
        param_dict["limit"] = limit
        
        sql = text(" ".join(sql_parts))
        result = conn.execute(sql, param_dict)
        
        segments = []
        for row in result:
            meta = None
            if row.meta_data:
                try:
                    if isinstance(row.meta_data, str):
                        meta = json.loads(row.meta_data)
                    elif isinstance(row.meta_data, dict):
                        meta = row.meta_data
                except Exception:
                    meta = None
            
            segments.append(
                MemorySegmentData(
                    segment_id=str(row.segment_id),
                    memory_type=str(row.memory_type),
                    related_id=str(row.related_id) if row.related_id else None,
                    content=str(row.content) if row.content else "",
                    metadata=meta,
                    created_at=_safe_parse_datetime(row.created_at),
                    score=float(row.score),
                )
            )
        return segments

    def get_all(
        self,
        memory_type: str | None = None,
        related_id: str | None = None,
        limit: int | None = None,
    ) -> list[MemorySegmentData]:
        with get_session() as db:
            q = db.query(MemorySegment)

            if memory_type:
                q = q.filter(MemorySegment.memory_type == memory_type)
            if related_id:
                q = q.filter(MemorySegment.related_id == related_id)

            q = q.order_by(MemorySegment.created_at.desc())

            if limit:
                q = q.limit(limit)

            rows = q.all()
            return [MemorySegmentData.from_orm(row) for row in rows]

    def add_segment(
        self,
        memory_type: str,
        content: str,
        related_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        segment_id = str(uuid.uuid4())
        
        # 对内容进行 jieba 分词
        tokenized_content = self._tokenize_text(content)

        with get_session() as db:
            segment = MemorySegment(
                segment_id=segment_id,
                memory_type=memory_type,
                related_id=related_id,
                content=content,
                meta_data=metadata,
            )
            db.add(segment)
            db.commit()
            db.refresh(segment)
        
        # 同步到 FTS 表
        with engine.connect() as conn:
            conn.execute(
                text("INSERT INTO memory_segments_fts (segment_id, content) VALUES (:segment_id, :content)"),
                {"segment_id": segment_id, "content": tokenized_content}
            )
            conn.commit()

        return segment_id

    def update_segment(
        self,
        segment_id: str,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        with get_session() as db:
            segment = (
                db.query(MemorySegment)
                .filter(MemorySegment.segment_id == segment_id)
                .first()
            )
            if not segment:
                return False

            old_content = segment.content
            if content is not None:
                segment.content = content
            if metadata is not None:
                segment.meta_data = metadata

            db.commit()
            
            # 如果内容有更新，也同步更新 FTS
            if content is not None and content != old_content:
                tokenized_content = self._tokenize_text(content)
                
                with engine.connect() as conn:
                    conn.execute(
                        text("DELETE FROM memory_segments_fts WHERE segment_id = :segment_id"),
                        {"segment_id": segment_id}
                    )
                    conn.execute(
                        text("INSERT INTO memory_segments_fts (segment_id, content) VALUES (:segment_id, :content)"),
                        {"segment_id": segment_id, "content": tokenized_content}
                    )
                    conn.commit()
            
            return True

    def delete_segment(self, segment_id: str) -> bool:
        with get_session() as db:
            segment = (
                db.query(MemorySegment)
                .filter(MemorySegment.segment_id == segment_id)
                .first()
            )
            if not segment:
                return False

            db.delete(segment)
            db.commit()
        
        # 同时从 FTS 表删除
        with engine.connect() as conn:
            conn.execute(
                text("DELETE FROM memory_segments_fts WHERE segment_id = :segment_id"),
                {"segment_id": segment_id}
            )
            conn.commit()
            
        return True

    def delete_by_related_id(self, memory_type: str, related_id: str) -> int:
        with get_session() as db:
            segments = (
                db.query(MemorySegment)
                .filter(MemorySegment.memory_type == memory_type)
                .filter(MemorySegment.related_id == related_id)
                .all()
            )
            
            # 先获取所有要删除的 segment_id
            segment_ids = [seg.segment_id for seg in segments]
            
            count = len(segments)
            for segment in segments:
                db.delete(segment)
            
            db.commit()
        
        # 同时从 FTS 表删除
        if segment_ids:
            with engine.connect() as conn:
                for segment_id in segment_ids:
                    conn.execute(
                        text("DELETE FROM memory_segments_fts WHERE segment_id = :segment_id"),
                        {"segment_id": segment_id}
                    )
                conn.commit()
            
        return count

    def _escape_fts_query(self, query: str) -> str:
        if not query:
            return ""

        special_chars = ['"', "'", '*', '^', '(', ')', '{', '}', '[', ']', ':', ';', '&', '|', '!', ',']
        escaped = query
        for char in special_chars:
            escaped = escaped.replace(char, " ")

        words = escaped.split()
        if not words:
            return ""

        return " OR ".join(f'"{word}"' for word in words if word)


memory_searcher = MemorySearcher()
