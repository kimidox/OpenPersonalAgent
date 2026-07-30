from unittest import TestCase

from skill import SkillDefinition, build_skills_catalog_text


class Test(TestCase):
    def test_build_skills_catalog_text(self):
        skill=SkillDefinition(skill_id='1',name="test",description="test",body='body_content')
        skill_2 = SkillDefinition(skill_id='2', name="test", description="test", body='body_content')
        skills=[skill,skill_2]
        res=build_skills_catalog_text(skills)
        print(res)