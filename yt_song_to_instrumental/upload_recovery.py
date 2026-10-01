"""Journal resumable sessions before sending bytes, and results before returning.

A lost final response is recovered by querying the same session. An expired
session is reconciled against the authenticated channel before any new insert.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
import hashlib
import json
import time

from yt_song_to_instrumental import constants as C


_active = ContextVar(C.UPLOAD_RECOVERY_UPLOAD_JOURNAL, default=None)


@contextmanager
def upload_journal(history, video_id, model, kind):
    journal = (history._conn, video_id, model, kind)
    token = _active.set(journal)
    try:
        yield journal
    finally:
        _active.reset(token)


class Journal:
    def __init__(self, connection, video_id, model, kind):
        self.db = connection
        self.key = (video_id, model, kind)
        self.db.execute(C.UPLOAD_RECOVERY_SCHEMA)
        self.db.commit()
        row = self.db.execute(C.UPLOAD_RECOVERY_LOAD_QUERY, self.key).fetchone()
        self.value = json.loads(row[C.UPLOAD_RECOVERY_NUMBER_0]) if row else {}

    def save(self, **changes):
        self.value.update(changes)
        self.db.execute(C.UPLOAD_RECOVERY_SAVE_QUERY, (*self.key, json.dumps(self.value)))
        self.db.commit()


class JournalTransport:
    def __init__(self, transport, journal):
        self.transport = transport
        self.journal = journal

    def request(self, uri, method=C.UPLOAD_RECOVERY_GET, body=None, headers=None, **kwargs):
        response, content = self.transport.request(uri, method=method, body=body, headers=headers, **kwargs)
        if response.status in (C.UPLOAD_RECOVERY_HTTP_OK, C.UPLOAD_RECOVERY_HTTP_CREATED, C.UPLOAD_RECOVERY_HTTP_INCOMPLETE) and response.get(C.UPLOAD_RECOVERY_LOCATION):
            # This commit precedes the client's very first media PUT.
            self.journal.save(session=response[C.UPLOAD_RECOVERY_LOCATION])
        if method == C.UPLOAD_RECOVERY_PUT and response.status in (C.UPLOAD_RECOVERY_HTTP_OK, C.UPLOAD_RECOVERY_HTTP_CREATED):
            result = json.loads(content)
            self.journal.save(result=result[C.UPLOAD_RECOVERY_ID])
        return response, content


def reconcile_expired(service, journal):
    channels = service.channels().list(part=C.UPLOAD_RECOVERY_CONTENTDETAILS, mine=True).execute()
    playlist = channels[C.UPLOAD_RECOVERY_ITEMS][C.UPLOAD_RECOVERY_NUMBER_0][C.UPLOAD_RECOVERY_CONTENTDETAILS][C.UPLOAD_RECOVERY_RELATEDPLAYLISTS][C.UPLOAD_RECOVERY_UPLOADS]
    token = None
    matches = set()
    expected = journal.value[C.UPLOAD_RECOVERY_BODY][C.UPLOAD_RECOVERY_SNIPPET]
    while True:
        page = service.playlistItems().list(part=C.UPLOAD_RECOVERY_CONTENTDETAILS, playlistId=playlist, maxResults=C.UPLOAD_RECOVERY_PAGE_SIZE, pageToken=token).execute()
        ids = [item[C.UPLOAD_RECOVERY_CONTENTDETAILS][C.UPLOAD_RECOVERY_VIDEOID] for item in page[C.UPLOAD_RECOVERY_ITEMS]]
        if ids:
            videos = service.videos().list(part=C.UPLOAD_RECOVERY_SNIPPET, id=C.UPLOAD_RECOVERY_ID_SEPARATOR.join(ids)).execute()
            for item in videos[C.UPLOAD_RECOVERY_ITEMS]:
                snippet = item[C.UPLOAD_RECOVERY_SNIPPET]
                published = datetime.fromisoformat(snippet[C.UPLOAD_RECOVERY_PUBLISHEDAT].replace(C.UPLOAD_RECOVERY_Z, C.UPLOAD_RECOVERY_UTC_OFFSET)).timestamp()
                if (snippet[C.UPLOAD_RECOVERY_TITLE] == expected[C.UPLOAD_RECOVERY_TITLE] and snippet[C.UPLOAD_RECOVERY_DESCRIPTION] == expected[C.UPLOAD_RECOVERY_DESCRIPTION]
                        and published >= journal.value[C.UPLOAD_RECOVERY_STARTED] - C.UPLOAD_RECOVERY_CLOCK_SKEW_SECONDS):
                    matches.add(item[C.UPLOAD_RECOVERY_ID])
        token = page.get(C.UPLOAD_RECOVERY_NEXTPAGETOKEN)
        if not token:
            break
    if len(matches) > C.UPLOAD_RECOVERY_NUMBER_1:
        raise RuntimeError(C.UPLOAD_RECOVERY_AMBIGUOUS_ERROR)
    if matches:
        result = matches.pop()
        journal.save(result=result)
        return result
    # A complete, successful channel read is required, followed by a visibility
    # grace period measured from the first expired-session observation.
    expired = journal.value.get(C.UPLOAD_RECOVERY_EXPIRED)
    if expired is None:
        journal.save(expired=time.time())
        raise RuntimeError(C.UPLOAD_RECOVERY_PENDING_ERROR)
    if time.time() - expired < C.UPLOAD_RECOVERY_VISIBILITY_GRACE_SECONDS:
        raise RuntimeError(C.UPLOAD_RECOVERY_PENDING_ERROR)
    journal.save(session=None, expired=None, started=time.time())
    return None


def recovered_attempt(service, request, file_path, body):
    journal = _active.get()
    if journal is None:
        return None
    journal = Journal(*journal)
    if journal.value.get(C.UPLOAD_RECOVERY_RESULT):
        return journal.value[C.UPLOAD_RECOVERY_RESULT]
    with file_path.open(C.UPLOAD_RECOVERY_RB) as stream:
        digest = hashlib.file_digest(stream, C.UPLOAD_RECOVERY_SHA256).hexdigest()
    session = journal.value.get(C.UPLOAD_RECOVERY_SESSION)
    transport = JournalTransport(request.http, journal)
    if session:
        # Query before checking the local file: a completed remote upload is
        # authoritative even when a render was regenerated after the crash.
        response, content = transport.request(session, method=C.UPLOAD_RECOVERY_PUT, headers={C.UPLOAD_RECOVERY_CONTENT_RANGE: C.UPLOAD_RECOVERY_STATUS_RANGE, C.UPLOAD_RECOVERY_CONTENT_LENGTH: C.UPLOAD_RECOVERY_EMPTY_CONTENT_LENGTH})
        if response.status in (C.UPLOAD_RECOVERY_HTTP_MISSING, C.UPLOAD_RECOVERY_HTTP_GONE):
            result = reconcile_expired(service, journal)
            if result:
                return result
            session = None
        else:
            _, result = request._process_response(response, content)
            if result:
                return result[C.UPLOAD_RECOVERY_ID]
            if digest != journal.value[C.UPLOAD_RECOVERY_DIGEST]:
                # The query proved this session incomplete. Start over rather
                # than appending different bytes to the old partial object.
                session = None
                request.resumable_progress = C.UPLOAD_RECOVERY_NUMBER_0
    if not session:
        journal.save(session=None, body=body, digest=digest, started=time.time(), expired=None)
    request.resumable_uri = session
    response = None
    while response is None:
        _, response = request.next_chunk(http=transport)
    journal.save(result=response[C.UPLOAD_RECOVERY_ID])
    return response[C.UPLOAD_RECOVERY_ID]
