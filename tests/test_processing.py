from unittest import TestCase

from skill import SkillDefinition, build_skills_catalog_text


class Test(TestCase):
    def test_build_skills_catalog_text_empty(self):
        """空 skills 列表应返回无可用 Skill 的提示"""
        res = build_skills_catalog_text([])
        assert "没有可用 Skill" in res
        assert "<Skills>" not in res

    def test_build_skills_catalog_text_with_skills(self):
        """非空 skills 列表应返回包含各 skill 信息的 catalog 文本"""
        skill = SkillDefinition(skill_id='1', name="test_skill", description="test_desc", body='body_content')
        skill_2 = SkillDefinition(skill_id='2', name="another_skill", description="another_desc", body='body_content')
        skills = [skill, skill_2]
        res = build_skills_catalog_text(skills)
        # 验证外层标签结构
        assert "<Skills>" in res
        assert "</Skills>" in res
        # 验证每个 skill 的信息被包含
        assert "<id>1</id>" in res
        assert "<id>2</id>" in res
        assert "<name>test_skill</name>" in res
        assert "<name>another_skill</name>" in res
        assert "<desc>test_desc</desc>" in res
        assert "<desc>another_desc</desc>" in res
        # 验证前缀提示文本
        assert "可用 Skill 列表" in res
        # 验证 catalog 文本非空且有实质内容
        assert len(res) > 50, "catalog 文本长度应大于 50 字符"
        # 验证 XML 标签正确闭合（<Skills> 在 </Skills> 之前）
        assert res.index("<Skills>") < res.index("</Skills>"), "<Skills> 应在 </Skills> 之前"