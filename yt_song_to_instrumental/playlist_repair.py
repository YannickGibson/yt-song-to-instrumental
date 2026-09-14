"""Budgeted, restart-safe playlist repair inside the existing managed worker."""
import logging
import time
from bisect import bisect_left

from yt_song_to_instrumental.constants import (
    PLAYLIST_PAGE_SIZE, PLAYLIST_REPAIR_MAX_MOVES, PLAYLIST_VERIFY_DELAYS,
    PLAYLIST_REPAIR_RETRY_SECONDS,
)
from yt_song_to_instrumental.playlists import upload_ranks
from yt_song_to_instrumental.youtube_quota import QuotaLedger, QuotaReserved

logger = logging.getLogger(__name__)


def list_items(service, playlist_id):
    items = []
    token = None
    seen = set()
    while True:
        response = service.playlistItems().list(
            part='snippet', playlistId=playlist_id, maxResults=PLAYLIST_PAGE_SIZE,
            pageToken=token,
        ).execute()
        items.extend(response['items'])
        token = response.get('nextPageToken')
        if not token:
            return items
        if token in seen:
            raise ValueError('Repeated playlist page token')
        seen.add(token)


def desired_order(items, ranks, anchor_positions=None):
    """Sort known items; preserve unknown items at their existing absolute slots."""
    known = sorted(
        (item for item in items if item['snippet']['resourceId']['videoId'] in ranks),
        key=lambda item: ranks[item['snippet']['resourceId']['videoId']],
    )
    anchor_positions = anchor_positions or {}
    result = [None] * len(items)
    for index, item in enumerate(items):
        if item['snippet']['resourceId']['videoId'] not in ranks:
            position = anchor_positions.get(item['id'])
            if position is None:
                position = index
            if position >= len(items) or result[position] is not None:
                raise ValueError('Unknown-item anchors require a fresh inventory')
            result[position] = item
    ordered = iter(known)
    return [next(ordered) if item is None else item for item in result]


def _lis(sequence, ranks):
    tails = []
    indices = []
    previous = {}
    for item in sequence:
        value = ranks[item]
        index = bisect_left(tails, value)
        previous[item] = indices[index - 1] if index else None
        if index == len(tails):
            tails.append(value)
            indices.append(item)
        else:
            tails[index] = value
            indices[index] = item
    keep = set()
    item = indices[-1] if indices else None
    while item is not None:
        keep.add(item)
        item = previous[item]
    return keep


def plan_moves(current, target):
    """N minus LIS moves. Stable playlist-item IDs handle duplicate video IDs."""
    ranks = {item: index for index, item in enumerate(target)}
    if len(ranks) != len(target) or set(current) != set(target):
        raise ValueError('Playlist membership changed or item IDs are not unique')
    keep = _lis(current, ranks)
    working = list(current)
    moves = []
    # Insert non-LIS items immediately before the already-positioned successor.
    successor = None
    for item in reversed(target):
        if item not in keep:
            working.remove(item)
            position = working.index(successor) if successor is not None else len(working)
            working.insert(position, item)
            moves.append((item, position))
        successor = item
    if working != target:
        raise ValueError('Move plan did not reach target')
    return moves


def repair_due(service, history):
    ledger = getattr(service, 'quota_ledger', None)
    if not isinstance(ledger, QuotaLedger):
        return
    day = ledger.day()
    with ledger.lock(), ledger.repair_lane():
        with ledger.connect() as db:
            row = db.execute('SELECT status, moves FROM repair_runs WHERE day=?', (day,)).fetchone()
            if row and row[0] == 'retry_pending':
                retry = db.execute('SELECT not_before FROM repair_retry WHERE day=?', (day,)).fetchone()
                if retry and ledger.now().timestamp() < retry[0]:
                    return
            elif row and row[0] != 'running':
                return
            used_moves = row[1] if row else 0
            # Resume by rereading live state, never by replaying an old position.
            db.execute('INSERT OR REPLACE INTO repair_runs VALUES (?, ?, ?, NULL, NULL, NULL)',
                       (day, 'running', used_moves))
        checked = 0
        unknown = 0
        remaining = 0
        status = 'complete'
        ranks = upload_ranks(history, ledger)
        rows = history._conn.execute(
            "SELECT youtube_playlist_id FROM playlists ORDER BY CASE playlist_type "
            "WHEN 'album' THEN 0 WHEN 'artist' THEN 1 ELSE 2 END, id"
        ).fetchall()
        try:
            for row in rows:
                if ledger.day() != day:
                    status = 'day_changed'
                    break
                playlist_id = row[0]
                items = list_items(service, playlist_id)
                with ledger.connect() as db:
                    for index, item in enumerate(items):
                        if item['snippet']['resourceId']['videoId'] not in ranks:
                            db.execute('INSERT OR IGNORE INTO repair_anchors VALUES (?, ?, ?)',
                                       (playlist_id, item['id'], index))
                    anchors = dict(db.execute('SELECT item_id, position FROM repair_anchors WHERE playlist_id=?',
                                              (playlist_id,)))
                target = desired_order(items, ranks, anchors)
                unknown += sum(item['snippet']['resourceId']['videoId'] not in ranks for item in items)
                target_ids = [item['id'] for item in target]
                current_ids = [item['id'] for item in items]
                moves = plan_moves(current_ids, target_ids)
                by_id = {item['id']: item for item in items}
                for item_id, position in moves:
                    if ledger.day() != day:
                        status = "day_changed"
                        break
                    if used_moves >= PLAYLIST_REPAIR_MAX_MOVES:
                        status = 'daily_cap'
                        break
                    item = by_id[item_id]
                    with ledger.connect() as db:
                        event = db.execute(
                            'INSERT INTO repair_events(day, playlist_id, item_id, position, state) VALUES (?, ?, ?, ?, ?)',
                            (day, playlist_id, item_id, position, 'intent'),
                        ).lastrowid
                        # Count attempted moves before sending, even on ambiguous errors.
                        used_moves += 1
                        db.execute('UPDATE repair_runs SET moves=? WHERE day=?', (used_moves, day))
                    service.playlistItems().update(part='snippet', body={
                        'id': item_id,
                        'snippet': {
                            'playlistId': playlist_id,
                            'resourceId': item['snippet']['resourceId'],
                            'position': position,
                        },
                    }).execute()
                    current_ids.remove(item_id)
                    current_ids.insert(position, item_id)
                    with ledger.connect() as db:
                        db.execute('UPDATE repair_events SET state=? WHERE id=?', ('applied', event))
                # Verify the exact membership and order after every changed playlist/slice.
                if moves:
                    for delay in PLAYLIST_VERIFY_DELAYS:
                        if delay:
                            time.sleep(delay)
                        actual = list_items(service, playlist_id)
                        if [item['id'] for item in actual] == current_ids:
                            break
                    else:
                        raise RuntimeError('Playlist readback differs from the applied move plan')
                    with ledger.connect() as db:
                        db.execute("UPDATE repair_events SET state='verified' WHERE day=? AND playlist_id=? AND state='applied'",
                                   (day, playlist_id))
                if current_ids == target_ids:
                    with ledger.connect() as db:
                        db.execute("UPDATE repair_events SET state='verified' WHERE playlist_id=? AND state='applied'", (playlist_id,))
                        db.execute("UPDATE repair_events SET state='reconciled' WHERE playlist_id=? AND state='intent'", (playlist_id,))
                checked += 1
                playlist_remaining = len(plan_moves(current_ids, target_ids))
                remaining += playlist_remaining
                with ledger.connect() as db:
                    db.execute("INSERT OR REPLACE INTO repair_playlists VALUES (?, ?, ?)",
                               (playlist_id, playlist_remaining, ledger.now().isoformat()))
                if status in ('daily_cap', 'day_changed'):
                    break
        except QuotaReserved:
            status = 'quota_cap'
        except Exception as error:
            status = 'retry_pending'
            with ledger.connect() as db:
                db.execute('INSERT OR REPLACE INTO repair_retry VALUES (?, ?)',
                           (day, ledger.now().timestamp() + PLAYLIST_REPAIR_RETRY_SECONDS))
            logger.warning('Playlist repair paused: %s', type(error).__name__)
        with ledger.connect() as db:
            db.execute('UPDATE repair_runs SET status=?, remaining=?, unknown=?, checked=? WHERE day=?',
                       (status, remaining if status == 'complete' else None, unknown, checked, day))
        logger.info('Playlist repair batch: status=%s moves=%d checked=%d unknown=%d',
                    status, used_moves, checked, unknown)
