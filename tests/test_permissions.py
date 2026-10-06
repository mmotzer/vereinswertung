import json
import tempfile
import time
import unittest
from pathlib import Path
from werkzeug.security import generate_password_hash
from app import create_app
import storage


class PermissionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'club.sqlite'
        self.app=create_app(dict(TESTING=True,DATABASE=str(self.path),BOOTSTRAP_TOKEN='x'*32,SECURE_COOKIE=False,PUBLIC_ORIGIN='http://localhost'))
        self.client=self.app.test_client();self.headers={'Origin':'http://localhost'}
        with storage.open_db(self.path) as db:
            for name,role in [('admin','admin'),('director','director'),('member','member')]:
                db.execute('INSERT INTO users(username,password,role,created) VALUES(?,?,?,?)',(name,generate_password_hash('test-password-123'),role,time.time()))
        self.login('admin')

    def tearDown(self):self.temp.cleanup()

    def login(self,name):
        response=self.client.post('/api/login',json=dict(username=name,password='test-password-123'),headers={'Origin':'http://localhost'})
        self.assertEqual(response.status_code,200)
        self.headers={'Origin':'http://localhost','X-CSRF-Token':response.json['csrf']}

    def change(self,uid,**data):return self.client.post('/api/users/'+str(uid),json=data,headers=self.headers)

    def test_deny_overrides_director_template(self):
        self.assertEqual(self.change(2,permissions=dict(import_=False)).status_code,400)
        self.assertEqual(self.change(2,permissions={'import':False,'approve':False,'export':False}).status_code,200)
        self.login('director')
        for path in ('/api/import/inspect','/api/lichess/inspect'):
            self.assertEqual(self.client.post(path,json={},headers=self.headers).status_code,403)
        self.assertEqual(self.client.get('/api/export.csv').status_code,403)
        self.assertEqual(self.client.get('/api/rankings').status_code,200)

    def test_allow_member_backup_without_user_management(self):
        self.assertEqual(self.change(3,permissions={'backup':True}).status_code,200)
        self.login('member')
        with self.client.get('/api/backup') as response:self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.get('/api/users').status_code,403)

    def test_last_administrator_cannot_remove_access(self):
        for changes in (dict(role='member'),dict(permissions={'manage_users':False}),dict(active=False)):
            self.assertEqual(self.change(1,**changes).status_code,400)
        self.assertEqual(self.client.get('/api/users').status_code,200)

    def test_changes_revoke_sessions_and_log_rights(self):
        member=self.app.test_client()
        member.post('/api/login',json=dict(username='member',password='test-password-123'),headers={'Origin':'http://localhost'})
        self.assertEqual(self.change(3,role='director',permissions={'undo':False}).status_code,200)
        self.assertEqual(member.get('/api/rankings').status_code,401)
        with storage.open_db(self.path) as db:
            detail=db.execute("SELECT detail FROM audit WHERE action='user_update' ORDER BY id DESC").fetchone()[0]
            self.assertIn('undo',detail);self.assertIn('director',detail)

    def test_approve_does_not_allow_direct_import(self):
        self.assertEqual(self.change(3,permissions={'approve':True}).status_code,200)
        self.login('member')
        self.assertEqual(self.client.post('/api/lichess/inspect',json={},headers=self.headers).status_code,403)
        # Authorized review proceeds to validation, without needing import rights.
        response=self.client.post('/api/lichess/inspect',json={'submission_id':999},headers=self.headers)
        self.assertEqual(response.status_code,400)

    def test_view_can_be_denied(self):
        self.assertEqual(self.change(3,permissions={'view':False}).status_code,200)
        self.login('member')
        self.assertEqual(self.client.get('/api/rankings').status_code,403)


if __name__=='__main__':unittest.main()
