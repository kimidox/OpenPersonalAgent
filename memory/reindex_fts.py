from database import init_db, get_session, engine
from sqlalchemy import text
from memory.searcher import MemorySearcher
from database.models import MemorySegment
from logger import get_module_logger

logger = get_module_logger("MemoryReindex")


def reindex_all_memory_segments():
    """重新索引所有记忆片段到 FTS 表"""
    init_db()
    
    searcher = MemorySearcher()
    
    with get_session() as db:
        # 获取所有记忆片段
        segments = db.query(MemorySegment).all()
        total = len(segments)
        
        logger.info(f"找到 {total} 条记忆片段，开始重新索引...")
        
        # 清空 FTS 表
        with engine.connect() as conn:
            conn.execute(text("DELETE FROM memory_segments_fts"))
            conn.commit()
        
        # 重新添加到 FTS 表
        indexed = 0
        for seg in segments:
            try:
                tokenized_content = searcher._tokenize_text(seg.content)
                
                with engine.connect() as conn:
                    conn.execute(
                        text("INSERT INTO memory_segments_fts (segment_id, content) VALUES (:segment_id, :content)"),
                        {"segment_id": seg.segment_id, "content": tokenized_content}
                    )
                    conn.commit()
                
                indexed += 1
                if indexed % 10 == 0:
                    logger.debug(f"已索引 {indexed}/{total} 条...")
            
            except Exception as e:
                logger.error(f"索引 segment {seg.segment_id} 时出错: {e}")
        
        logger.info(f"完成！成功索引 {indexed}/{total} 条记忆片段")
        
        # 验证
        with engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM memory_segments_fts"))
            count = result.scalar()
            logger.info(f"FTS 表中现在有 {count} 条记录")


if __name__ == "__main__":
    reindex_all_memory_segments()
