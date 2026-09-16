from utter.history import History


def test_add_recent_delete_clear(tmp_path):
    history = History(tmp_path / "h.db")
    first = history.add("Hello", "hello", "m", 1.5)
    second = history.add("World", "world", "m", 0.5)
    recent = history.recent()
    assert [e.text for e in recent] == ["World", "Hello"]
    assert recent[0].id == second.id
    history.delete(first.id)
    assert [e.text for e in history.recent()] == ["World"]
    history.clear()
    assert history.count() == 0
    history.close()


def test_limit_trims_oldest(tmp_path):
    history = History(tmp_path / "h.db")
    for i in range(5):
        history.add(str(i), str(i), "m", 0.1, limit=3)
    assert [e.text for e in history.recent()] == ["4", "3", "2"]
    history.close()
