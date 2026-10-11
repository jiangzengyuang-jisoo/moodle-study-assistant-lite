"""Delivery regressions with temporary fictional state only."""
import unittest
import light
import test_light as fixtures
from test_light import state


class FinalContextTests(unittest.TestCase):
    setUp = fixtures.LightTests.setUp

    def test_global_course_paging_keeps_every_course_in_one_order(self):
        s=state()
        s["courses"]=[{"id":f"C{i:02}","name":"Synthetic course "+"N"*150,"current_topic":"T"*150}
                      for i in range(12,0,-1)]
        light.atom(light.STATE,s)
        ctx=light.context(maximum=2500)
        self.assertIn("courses",ctx["more"])
        rows=list(ctx["courses"]);offset=ctx["more"]["courses"]["offset"]
        while True:
            page=light.listing("courses",offset=offset,limit=3,revision=ctx["revision"])
            rows.extend(page["items"])
            if not page["has_more"]:break
            offset=page["next_offset"]
        self.assertEqual(light.listing_rows(s,"courses"),rows)
        self.assertEqual(12,len({r["id"] for r in rows}))

    def test_intro_and_activity_media_cannot_be_acknowledged_as_text_only(self):
        snap={"finished_at":"2030-01-01T00:00:00Z","collection_complete":True,
              "pages":[{"courseid":1,"course_id":"COURSE-A","sections":[]}],
              "assignments":{"courses":[{"id":1,"assignments":[{"id":55,"name":"Synthetic visual requirements",
                "intro":'<img src="https://example.invalid/intro.png">',
                "introattachments":[{"filename":"deadline.pdf"}],
                "activity":'<img src=https://example.invalid/activity.png>',
                "activityattachments":[{"filename":"instructions.pdf"}]}]}]}}
        light.atom(light.SNAPSHOT,snap)
        row=next(r for r in light.review_page()["items"] if r["id"]=="assignment:55")
        self.assertEqual({"intro","activity"},{v["field"] for v in row["media"]["images"]})
        self.assertTrue(all(v["read_with"]=="browser" and "discussionid" not in v for v in row["media"]["images"]))
        self.assertEqual(2,len(row["media"]["attachments"]))
        with self.assertRaisesRegex(ValueError,"图片或附件"):
            light.accept(row["id"],row["hash"],"Read text only",row["event_id"])
        self.assertTrue(any(r["event_id"]==row["event_id"] for r in light.pending()["items"]))
        light.accept(row["id"],row["hash"],"Read text and requirements",row["event_id"],"Synthetic visual review")
        self.assertFalse(any(r["event_id"]==row["event_id"] for r in light.pending()["items"]))

    def test_quiz_introfiles_and_all_text_fields_are_discoverable(self):
        media=light.media_requirements({"body":{"message":"Plain first field","intro":'<img src="quiz.png">',
            "description":'<img src="description.png">',"introfiles":[{"filename":"quiz.png"}]}})
        self.assertEqual(["description","intro"],[i["field"] for i in media["images"]])
        self.assertEqual("introfiles",media["attachments"][0]["field"])

    def test_forum_indices_match_parser_and_nonforum_images_use_browser(self):
        media=light.media_requirements({"body":{"id":30,"discussion_id":5,
            "message":'<img data-src="ignore.png" src="first.png?a=1&amp;b=2"><img src=second.png><img src=""><img src="third.png?x=&#49;">',
            "description":'<img src="other.png">'}})
        forum=[i for i in media["images"] if i["read_with"]=="forum_image"]
        self.assertEqual([0,1,2],[i["index"] for i in forum])
        self.assertEqual(["first.png?a=1&b=2","second.png","third.png?x=1"],[i["expected_src"] for i in forum])
        self.assertEqual("browser",media["images"][-1]["read_with"])


if __name__=="__main__":unittest.main()
