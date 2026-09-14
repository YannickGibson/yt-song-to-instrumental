from datetime import datetime, timezone
from itertools import permutations
from unittest.mock import MagicMock

import pytest

from yt_song_to_instrumental.history import HistoryDB
from yt_song_to_instrumental.playlist_repair import desired_order, plan_moves, repair_due
from yt_song_to_instrumental.youtube_quota import QuotaLedger, QuotaReserved, metered_request_builder


def item(name, video=None):
    return {'id': name, 'snippet': {'resourceId': {'kind': 'youtube#video', 'videoId': video or name}}}


def test_minimal_move_plan_all_small_permutations():
    target = list('abcde')
    for permutation in permutations(target):
        current = list(permutation)
        moves = plan_moves(current, target)
        for name, position in moves:
            current.remove(name)
            current.insert(position, name)
        assert current == target
        # Independent exhaustive subsequence oracle, not the planner's LIS implementation.
        longest = max(sum(bool(mask & (1 << i)) for i in range(5)) for mask in range(32)
                      if sorted(permutation[i] for i in range(5) if mask & (1 << i)) ==
                      [permutation[i] for i in range(5) if mask & (1 << i)])
        assert len(moves) == 5 - longest


def test_duplicate_videos_keep_distinct_playlist_membership():
    items = [item('i2', 'old'), item('i1', 'new'), item('i3', 'old')]
    target = desired_order(items, {'new': 0, 'old': 1})
    assert [i['id'] for i in target] == ['i1', 'i2', 'i3']


def test_unknown_anchor_survives_partial_batch_and_replan():
    target = desired_order([item('c'), item('x'), item('b'), item('a')], {'a': 0, 'b': 1, 'c': 2})
    current = [item('x'), item('c'), item('b'), item('a')]
    assert desired_order(current, {'a': 0, 'b': 1, 'c': 2}, {'x': 1}) == target


def test_quota_reservation_and_pacific_reset(tmp_path):
    now = [datetime(2026, 9, 14, 6, 59, tzinfo=timezone.utc)]
    ledger = QuotaLedger(tmp_path / 'quota.db', now=lambda: now[0])
    for _ in range(110):
        ledger.charge('youtube.playlistItems.insert')
    with pytest.raises(QuotaReserved):
        ledger.charge('youtube.videos.list')
    with ledger.repair_lane():
        ledger.charge('youtube.playlistItems.update')
    # Upload initiation is a separate bucket and remains available.
    ledger.charge('youtube.videos.insert')
    now[0] = datetime(2026, 9, 14, 7, 0, tzinfo=timezone.utc)
    ledger.charge('youtube.videos.list')
    assert ledger.day() == '2026-09-14'


def test_two_clients_share_budget_and_attempts_are_charged(tmp_path):
    a = QuotaLedger(tmp_path / 'quota.db')
    b = QuotaLedger(tmp_path / 'quota.db')
    a.charge('youtube.comments.insert', attempts=110)
    with pytest.raises(QuotaReserved):
        b.charge('youtube.comments.list')


def test_request_builder_counts_failed_http_attempt(tmp_path):
    ledger = QuotaLedger(tmp_path / 'quota.db')
    http = MagicMock()
    http.request.side_effect = RuntimeError('offline')
    request = metered_request_builder(ledger)(http, lambda *args: None, 'https://example.invalid',
                                            methodId='youtube.playlistItems.update')
    with pytest.raises(RuntimeError):
        request.execute()
    with ledger.connect() as db:
        assert db.execute('select units from quota_usage').fetchone()[0] == 50


class FakeAPI:
    def __init__(self, ledger, ids):
        self.quota_ledger = ledger
        self.ids = list(ids)
        self.fail_after_apply = False
        self.writes = 0

    def playlistItems(self):
        return self

    def list(self, **kwargs):
        def execute():
            self.quota_ledger.charge('youtube.playlistItems.list')
            return {'items': [item(i) for i in self.ids]}
        result = MagicMock()
        result.execute = execute
        return result

    def update(self, part, body):
        def execute():
            self.quota_ledger.charge('youtube.playlistItems.update')
            self.ids.remove(body['id'])
            self.ids.insert(body['snippet']['position'], body['id'])
            self.writes += 1
            if self.fail_after_apply:
                raise RuntimeError('ambiguous timeout')
            return body
        result = MagicMock()
        result.execute = execute
        return result


def seeded_history(tmp_path, size):
    history = HistoryDB(tmp_path / 'history.db')
    for index in range(size):
        name = f'v{index:03}'
        history.record_download(name, '', name, 'Artist', '', '', '', '', '',
                                release_date=f'{2025-index:04}0101')
        history.record_upload(name, 'model', name, 'private')
    history.record_playlist('artist', 'Artist', None, 'playlist')
    return history


def test_daily_cap_resumes_next_day_and_finishes(tmp_path):
    now = [datetime(2026, 9, 14, 12, tzinfo=timezone.utc)]
    ledger = QuotaLedger(tmp_path / 'quota.db', now=lambda: now[0])
    history = seeded_history(tmp_path, 80)
    api = FakeAPI(ledger, [f'v{i:03}' for i in reversed(range(80))])
    repair_due(api, history)
    assert api.writes == 75
    repair_due(api, history)
    assert api.writes == 75
    now[0] = datetime(2026, 9, 15, 12, tzinfo=timezone.utc)
    repair_due(api, history)
    assert api.ids == [f'v{i:03}' for i in range(80)]
    assert api.writes == 79
    with ledger.connect() as db:
        assert db.execute('select status from repair_runs where day=?', (ledger.day(),)).fetchone()[0] == 'complete'


def test_ambiguous_write_recovers_by_reading_remote_state(tmp_path):
    now = [datetime(2026, 9, 14, 12, tzinfo=timezone.utc)]
    ledger = QuotaLedger(tmp_path / 'quota.db', now=lambda: now[0])
    history = seeded_history(tmp_path, 3)
    api = FakeAPI(ledger, ['v002', 'v001', 'v000'])
    api.fail_after_apply = True
    repair_due(api, history)
    assert api.writes == 1
    api.fail_after_apply = False
    now[0] = datetime(2026, 9, 15, 12, tzinfo=timezone.utc)
    repair_due(api, history)
    assert api.ids == ['v000', 'v001', 'v002']
    assert api.writes == 2
