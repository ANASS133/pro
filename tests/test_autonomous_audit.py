import os
os.environ['DISABLE_CONDUCTOR_DAEMON'] = 'true'
from unittest.mock import MagicMock, patch
import pytest
from services.conductor_store import ConductorStore
from services.daily_search_runner import DailySearchRunner
from services.email_reply_monitor import EmailReplyMonitor
from services.conductor_engine import ConductorEngine
from services.conductor_whatsapp_liaison import ConductorWhatsAppLiaison

@pytest.fixture
def store(tmp_path):
    db = ConductorStore(tmp_path / 'audit.db')
    yield db
    db.close()

def job(company='Test GmbH'):
    return dict(client_id='candidate', job_title='Fachinformatiker', company=company,
                email='hr@example.org', score=.9, status='applied')

def test_no_fabricated_opportunities(store, tmp_path):
    runner = DailySearchRunner(tmp_path / 'exports', store)
    with patch.object(runner, '_extract_candidate_search_params', return_value=dict(full_name='Test',profession='Fachinformatiker',city='Berlin')):
        result = runner.run_daily_search_for_client('candidate')
    assert result['new_matches_count'] == 0
    assert result['discovery_mode'] == 'datasets_only'

def test_auto_apply_never_claims_submission(store, tmp_path):
    store.update_client_config('candidate', {'auto_apply': 1})
    runner = DailySearchRunner(tmp_path / 'exports', store)
    with patch.object(runner, '_extract_candidate_search_params', return_value=dict(full_name='Test',profession='Fachinformatiker',city='Berlin')), patch.object(runner, '_find_matches_from_datasets', return_value=[job()]), patch.object(runner, '_generate_cover_letter_for_match', return_value='test.pdf'), patch.object(runner, '_increment_client_applied_stats') as stats:
        result = runner.run_daily_search_for_client('candidate')
    assert result['auto_applied_count'] == 0
    assert result['submission_status'] == 'not_implemented'
    assert result['matches'][0]['status'] == 'staged_for_approval'
    stats.assert_not_called()

def test_live_scraper_contract_and_full_cache(store, tmp_path):
    runner = DailySearchRunner(tmp_path / 'exports', store)
    store.set_setting('use_live_scrapers', 'true')
    from scraper.ausbildung_de_scraper import AusbildungDeScraper
    with patch.object(AusbildungDeScraper, 'fetch_jobs', autospec=True, return_value=[dict(title='Fachinformatiker',company='Fresh',url='https://example.org/job')]) as fetch, patch.object(runner, '_extract_candidate_search_params', return_value=dict(full_name='Test',profession='Fachinformatiker',city='Berlin')), patch.object(runner, '_find_matches_from_datasets', return_value=[job()]*5):
        result = runner.run_daily_search_for_client('candidate', max_jobs=1, force_cover_letter=False)
    assert fetch.call_args.kwargs['keyword'] == 'Fachinformatiker'
    assert result['matches'][0]['company'] == 'Fresh'

def test_unrelated_and_ambiguous_mail_not_assigned(store):
    store.save_match(job())
    monitor = EmailReplyMonitor(store=store)
    with patch('services.email_reply_monitor.client_manager.list_clients', return_value=[]):
        assert monitor.correlate_with_client_matches('spam@other.org','','Other','','') == (None,'')
        second = job(); second['client_id'] = 'second'; store.save_match(second)
        assert monitor.correlate_with_client_matches('hr@example.org','','Test GmbH','','') == (None,'')

def test_repeated_mail_does_not_repeat_side_effects(store):
    store.save_match(job())
    monitor = EmailReplyMonitor(store=store)
    with patch.object(monitor, 'classify_email_content', return_value={'intent':'rejection','company':'Test GmbH'}), patch.object(monitor, '_update_client_reply_stats') as stats, patch('services.email_reply_monitor.client_manager.list_clients', return_value=[]):
        args = dict(message_id='unique',sender='hr@example.org',recipient='',subject='Absage',received_at='',body='Absage')
        monitor.process_incoming_message(**args)
        assert monitor.process_incoming_message(**args)['duplicate']
    stats.assert_called_once()

@pytest.mark.parametrize('status', ['connection_error','error','unconfigured_audit_mode'])
def test_inbox_failures_are_failed_tasks(store, status):
    monitor = MagicMock(); monitor.check_inbox.return_value = {'status':status}
    engine = ConductorEngine(store=store, email_monitor=monitor)
    assert not engine.check_inbox_now()['success']
    assert store.list_tasks()[0]['status'] == 'failed'
    assert not engine.retry_task(store.list_tasks()[0]['id'])['success']

def test_unknown_retry_is_not_success(store):
    task = store.create_task('unsupported')
    assert not ConductorEngine(store=store).retry_task(task['id'])['success']

def test_simulated_whatsapp_not_recorded_as_sent(store):
    service = MagicMock(); service.send_text_message.return_value = {'success':True,'simulated':True,'provider_message_id':'sim'}
    liaison = ConductorWhatsAppLiaison(store=store,wa_store=MagicMock(),wa_service=service)
    assert not liaison._dispatch_and_record('candidate','49123456789','Test','hello','test','key')
    assert not store.has_notification_been_sent('key')

def test_imap_fetch_processes_real_mime_and_deduplicates(store):
    monitor = EmailReplyMonitor(user='test',password='test',store=store)
    conn = MagicMock()
    conn.select.return_value = ('OK', [b'1'])
    conn.search.return_value = ('OK',[b'1'])
    conn.fetch.return_value = ('OK',[(b'1',b'Message-ID: <audit>\r\nFrom: hr@example.org\r\nTo: candidate@example.net\r\nSubject: Absage\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nLeider eine Absage')])
    with patch.object(monitor, '_open_imap_connection', return_value=conn), patch.object(monitor, 'classify_email_content', return_value={'intent':'rejection'}), patch('services.email_reply_monitor.client_manager.list_clients', return_value=[]):
        assert monitor.check_inbox()['processed_count'] == 1
        assert monitor.check_inbox()['processed_count'] == 0
    conn.fetch.assert_called_with(b'1','(RFC822)')

@pytest.mark.parametrize('operation', ['select', 'search', 'fetch'])
def test_imap_protocol_failures_are_visible(store, operation):
    monitor = EmailReplyMonitor(user='test', password='test', store=store)
    conn = MagicMock()
    conn.select.return_value = ('OK', [b'1'])
    conn.search.return_value = ('OK', [b'1'])
    getattr(conn, operation).return_value = ('NO', [])
    with patch.object(monitor, '_open_imap_connection', return_value=conn):
        result = monitor.check_inbox()
    assert result['status'] in ('error', 'partial_error')
    conn.logout.assert_called_once()

def test_whatsapp_configured_path_posts_to_meta(store):
    from services.whatsapp_service import whatsapp_service
    response = MagicMock(status_code=200, content=b'{}')
    response.json.return_value = {'messages': [{'id': 'wamid.audit'}]}
    with patch.object(whatsapp_service, 'phone_number_id', 'test-number'), patch.object(whatsapp_service, 'access_token', 'test-token'), patch.object(whatsapp_service.session, 'post', return_value=response) as post:
        result = whatsapp_service.send_text_message('49123456789', 'audit')
    assert result['success'] and not result.get('simulated')
    assert post.call_args.args[0].endswith('/test-number/messages')
    assert post.call_args.kwargs['json']['text']['body'] == 'audit'

def test_worker_executes_due_search_and_inbox(store):
    runner = MagicMock()
    runner.run_daily_search_for_client.return_value = {'new_matches_count': 0}
    monitor = MagicMock()
    monitor.check_inbox.return_value = {'status': 'success', 'processed_count': 0}
    engine = ConductorEngine(store=store, search_runner=runner, email_monitor=monitor)
    def finish():
        engine._stop_event.set()
    with patch('services.conductor_engine.client_manager.list_clients', return_value=[{'id': 'candidate'}]), patch.object(engine, '_retry_failed_tasks', side_effect=finish):
        engine._worker_loop()
    runner.run_daily_search_for_client.assert_called_once()
    monitor.check_inbox.assert_called_once()
    assert all(t['status'] == 'completed' for t in store.list_tasks())
