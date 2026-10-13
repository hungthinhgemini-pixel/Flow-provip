import json

from flowprovip.capcut.draft import Clip, DraftBuilder


def test_draft_structure(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"x")
    vid = tmp_path / "b.mp4"
    vid.write_bytes(b"x")
    audio = tmp_path / "v.mp3"
    audio.write_bytes(b"x")
    clips = [Clip(str(img), 0, 4, "Xin chào"), Clip(str(vid), 4, 10, "thế giới", media_duration=8.0)]
    b = DraftBuilder()
    b.add_visual_track(clips)
    b.add_audio(audio, 10.0)
    b.add_subtitles(clips)
    folder = b.save(tmp_path / "drafts", "Test: draft")
    content = json.loads((folder / "draft_content.json").read_text(encoding="utf-8"))
    assert (folder / "draft_meta_info.json").exists()
    assert content["duration"] == 10_000_000
    kinds = [t["type"] for t in content["tracks"]]
    assert kinds == ["video", "audio", "text"]
    video = content["tracks"][0]["segments"]
    assert video[1]["target_timerange"] == {"start": 4_000_000, "duration": 6_000_000}
    assert video[1]["source_timerange"]["duration"] == 6_000_000
    mats = {m["id"]: m for m in content["materials"]["videos"]}
    assert mats[video[0]["material_id"]]["type"] == "photo"
    ids = {m["id"] for k in content["materials"].values() if isinstance(k, list) for m in k}
    for track in content["tracks"]:
        for seg in track["segments"]:
            assert seg["material_id"] in ids
            assert all(r in ids for r in seg["extra_material_refs"])
    text = json.loads(content["materials"]["texts"][0]["content"])
    assert text["text"] == "Xin chào"


def test_short_video_slowed_down(tmp_path):
    vid = tmp_path / "b.mp4"
    vid.write_bytes(b"x")
    b = DraftBuilder()
    b.add_visual_track([Clip(str(vid), 0, 10, media_duration=5.0)])
    seg = b.tracks[0]["segments"][0]
    assert seg["speed"] == 0.5 and seg["source_timerange"]["duration"] == 5_000_000
