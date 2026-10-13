from flowprovip.audio.scenes import Segment, Word, build_scenes, parse_srt, scenes_to_srt
from flowprovip.jobs import Kind, tasks_from_text


def test_merge_short_and_cover_timeline():
    segs = [Segment(0.5, 1.5, "Xin chào."), Segment(1.6, 3.0, "Hôm nay"),
            Segment(3.2, 9.0, "chúng ta nói về lịch sử."), Segment(9.1, 10.0, "Hết.")]
    scenes = build_scenes(segs, 3.0, 8.0, total_duration=11.0)
    assert scenes[0].start == 0.0
    assert scenes[-1].end == 11.0
    for a, b in zip(scenes, scenes[1:]):
        assert a.end == b.start
    assert all(s.duration <= 8.0 + 1e-6 for s in scenes[:-1])


def test_split_long_segment_by_words():
    words = [Word(i, i + 0.9, f" w{i}" + ("," if i == 5 else "")) for i in range(20)]
    seg = Segment(0, 19.9, "".join(w.text for w in words), words)
    scenes = build_scenes([seg], 3.0, 8.0)
    assert len(scenes) >= 3
    assert all(s.duration <= 8.5 for s in scenes)


def test_srt_roundtrip():
    segs = [Segment(0, 2.5, "a"), Segment(2.5, 6.0, "b c")]
    scenes = build_scenes(segs, 0.1, 10)
    back = parse_srt(scenes_to_srt(scenes))
    assert [s.text for s in back] == ["a", "b c"]
    assert back[1].start == 2.5 and back[1].end == 6.0


def test_tasks_from_text_lines_and_csv():
    t = tasks_from_text("cat\n\ndog\n", Kind.IMAGE, "style", "4k")
    assert [x.prompt for x in t] == ["style, cat, 4k", "style, dog, 4k"]
    t = tasks_from_text("prompt,video_prompt\nhero,walks forward\n", Kind.IMAGE_VIDEO)
    assert t[0].prompt == "hero" and t[0].video_prompt == "walks forward"
