import base64
import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path

from app import create_app, backup_database
import storage
import club_roster
import trf


def player_line(number,name,rounds,rating=2200):
    line=list(' '*91)
    line[0:3]='001';line[4:8]=f'{number:4d}';line[9]='M'
    line[14:47]=f'{name:33}'[:33];line[48:52]=f'{rating:4d}'
    return ''.join(line)+''.join(f'{opp:4d} {color} {result}  ' for opp,color,result in rounds)


def fixture(day='2025-09-16',draw=False):
    return '\n'.join(['012 Vereinsabend','042 '+day,'052 '+day,
       player_line(1,'Alpha, Anna',[(3,'w','=' if draw else '1')],2500),
       player_line(2,'Beta, Ben',[(4,'b','1')],1000),
       player_line(3,'Gamma, Greta',[(1,'b','=' if draw else '0')],800),
       player_line(4,'Delta, David',[(2,'w','0')],2300)])


class ParserTests(unittest.TestCase):
    def test_sample_shape(self):
        parsed=trf.parse(fixture())
        self.assertEqual(len(parsed['players']),4)
        self.assertEqual(len(parsed['games']),2)
        self.assertEqual(parsed['games'][1]['white'],4)
        self.assertEqual(parsed['games'][1]['score'],0)

    def test_row_order_is_irrelevant(self):
        lines=fixture().splitlines()
        self.assertEqual(trf.parse(fixture())['games'],trf.parse('\n'.join(lines[:3]+list(reversed(lines[3:]))))['games'])

    def test_two_rounds_and_byes(self):
        text='\n'.join([player_line(1,'One',[(2,'w','1'),(0,'-','U')]),
                        player_line(2,'Two',[(1,'b','0'),(3,'b','=')]),
                        player_line(3,'Three',[(0,'-','U'),(2,'w','=')])])
        p=trf.parse(text)
        self.assertEqual(p['rounds'],2)
        self.assertEqual([g['round'] for g in p['games']],[1,2])
        self.assertEqual(len(p['skipped']),2)

    def test_forfeit_not_rated(self):
        text=fixture()+'\n'+player_line(5,'Five',[(6,'w','+')])+'\n'+player_line(6,'Six',[(5,'b','-')])
        p=trf.parse(text)
        self.assertEqual(len(p['games']),2)
        self.assertEqual(len(p['skipped']),1)

    def test_bad_result_and_color_rejected(self):
        for text in [fixture().replace('   3 w 1','   3 w 0'),
                     fixture().replace('   3 w 1','   3 b 1'),
                     fixture().replace('   3 w 1','   3 w Q'),
                     fixture().replace('   3 w 1','   3 w  '),
                     fixture().replace('   3 w 1','   9 w 1')]:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):trf.parse(text)

    def test_encoding(self):
        text=fixture().replace('Anna','Änna')
        self.assertEqual(trf.decode(text.encode('cp1252')),text)
        self.assertEqual(trf.decode(text.encode('utf-8-sig')),text)


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=str(Path(self.tmp.name)/'club.sqlite')
        self.app=create_app({'TESTING':True,'DATABASE':self.path,'BOOTSTRAP_TOKEN':'test-bootstrap-key-long-enough-123',
                             'SECURE_COOKIE':False,'PUBLIC_ORIGIN':''})
        self.client=self.app.test_client()
        self.csrf=''
        r=self.post('/api/setup',{'token':'test-bootstrap-key-long-enough-123','username':'admin','password':'long-password-for-test'})
        self.assertEqual(r.status_code,200,r.json)
        self.login('admin')

    def tearDown(self):
        self.tmp.cleanup()

    def post(self,path,data,client=None,csrf=None):
        return (client or self.client).post(path,json=data,headers={'Origin':'http://localhost','X-CSRF-Token':csrf if csrf is not None else self.csrf})

    def login(self,username,client=None):
        r=self.post('/api/login',{'username':username,'password':'long-password-for-test'},client=client)
        self.assertEqual(r.status_code,200,r.json)
        if client is None:self.csrf=r.json['csrf']
        return r.json['csrf']

    def payload(self,text=None,category='blitz',day='2025-09-16'):
        return {'content':base64.b64encode((text or fixture(day)).encode()).decode(), 'filename':'test.trf',
                'name':'Vereinsabend','category':category,'round_dates':[day],'mapping':{}}

    def preview(self,payload):
        r=self.post('/api/import/preview',payload)
        self.assertEqual(r.status_code,200,r.json)
        return r.json

    def commit(self,payload):
        p=self.preview(payload)
        r=self.post('/api/import/commit',{'token':p['token']})
        self.assertEqual(r.status_code,200,r.json)
        return r.json['tournament_id']

    def test_hide_cancelled_tournament_preserves_players_and_ratings(self):
        tid=self.commit(self.payload())
        self.assertEqual(self.post(f'/api/tournaments/{tid}/hide',{}).status_code,400)
        self.assertEqual(self.post(f'/api/tournaments/{tid}/undo',{'confirm':'Vereinsabend'}).status_code,200)
        before=self.client.get('/api/rankings').json
        with storage.open_db(self.path) as db:
            db.execute("UPDATE users SET role='director' WHERE username='admin'")
        self.assertEqual(self.post(f'/api/tournaments/{tid}/hide',{}).status_code,403)
        with storage.open_db(self.path) as db:
            db.execute("UPDATE users SET role='admin' WHERE username='admin'")
        self.assertEqual(self.post(f'/api/tournaments/{tid}/hide',{}).status_code,200)
        self.assertEqual(self.client.get('/api/tournaments').json['tournaments'],[])
        self.assertEqual(self.client.get('/api/rankings').json,before)
        with storage.open_db(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM players').fetchone()[0],4)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM games').fetchone()[0],2)

    def test_lichess_batch_consent_selection_atomicity_and_duplicate(self):
        from unittest.mock import patch
        import lichess_import
        self.commit(self.payload())
        players = {p['name']:p['id'] for p in self.client.get('/api/rankings').json['players']}
        mapping = {'Lichess: Anna':players['Alpha, Anna'],'Lichess: Ben':players['Beta, Ben']}
        def exported(gid,cat,stamp):
            return lichess_import.parse_game({'id':gid,'variant':'standard','speed':cat,'status':'mate','winner':'white',
                'lastMoveAt':stamp,'players':{'white':{'user':{'name':'Anna'}},'black':{'user':{'name':'Ben'}}}})
        items = [exported('abcdefgh','blitz',1758100000000),exported('ijklmnop','rapid',1758101000000)]
        with patch('lichess_import.fetch_games',return_value=items):
            inspect = self.post('/api/lichess/inspect',{'links':'links'}).json
        self.assertEqual(self.post('/api/import/commit',{'token':inspect['token']}).status_code,400)
        request = {'token':inspect['token'],'mapping':mapping,'selected':['abcdefgh','ijklmnop'],'consent':False}
        self.assertEqual(self.post('/api/lichess/preview',request).status_code,400)
        request['consent']=True
        before=self.client.get('/api/rankings').json
        preview=self.post('/api/lichess/preview',request)
        self.assertEqual(preview.status_code,200,preview.json)
        self.assertEqual(preview.json['count'],2)
        self.assertEqual([(p['id'],p['rating'],p['games']) for p in self.client.get('/api/rankings').json['players']],[(p['id'],p['rating'],p['games']) for p in before['players']])
        self.assertEqual(self.post('/api/import/commit',{'token':preview.json['token']}).status_code,200)
        self.assertEqual(len(self.client.get('/api/tournaments').json['tournaments']),3)
        self.assertEqual(self.post('/api/lichess/preview',request).status_code,400)
        with storage.open_db(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM players').fetchone()[0],4)

    def test_pwa_boot_assets_are_public_but_club_data_requires_login(self):
        anonymous=self.app.test_client()
        with anonymous.get('/sw.js') as response:
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.mimetype,'application/javascript')
            self.assertEqual(response.headers['Cache-Control'],'no-cache')
        with anonymous.get('/static/manifest.webmanifest') as response:
            self.assertEqual(response.mimetype,'application/manifest+json')
            manifest=json.loads(response.data)
            self.assertEqual(manifest['scope'],'/')
            self.assertEqual(manifest['display'],'standalone')
            self.assertEqual({icon['sizes'] for icon in manifest['icons']},{'192x192','512x512'})
        for path in ['/static/pwa.js','/static/offline.html','/static/offline.css','/static/icon-192.png','/static/icon-512.png']:
            with anonymous.get(path) as response:
                self.assertEqual(response.status_code,200,path)
        self.assertEqual(anonymous.get('/api/rankings').status_code,401)

    def test_lichess_details_are_restricted_to_directors(self):
        from flask import g, request
        import lichess_import
        trf_id=self.commit(self.payload())
        players=self.client.get('/api/rankings').json['players']
        item=lichess_import.parse_game({'id':'abcdefgh','variant':'standard','speed':'blitz','status':'mate','winner':'white',
            'lastMoveAt':1758100000000,'players':{'white':{'user':{'name':'Anna'}},'black':{'user':{'name':'Ben'}}}})
        item['mapping']={'1':players[0]['id'],'2':players[1]['id']}
        with storage.open_db(self.path) as db:
            owner=db.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
            tid=storage.import_tournament(db,item,owner)
        def viewer_for_test():
            if request.headers.get('X-Test-Viewer') and g.user:
                g.user={**g.user,'role':'viewer'}
        self.app.before_request_funcs[None].append(viewer_for_test)
        headers={'X-Test-Viewer':'1'}
        self.assertEqual([t['id'] for t in self.client.get('/api/tournaments',headers=headers).json['tournaments']],[trf_id])
        self.assertEqual(self.client.get(f'/api/tournaments/{tid}',headers=headers).status_code,403)
        profile=self.client.get(f"/api/players/{players[0]['id']}",headers=headers).json
        self.assertTrue(all(h['tournament_id']!=tid for h in profile['history']))
        self.assertEqual(profile['ratings']['blitz']['games'],2)
        for path in ['/api/lichess/inspect','/api/lichess/preview']:
            self.assertEqual(self.client.post(path,json={},headers={**headers,'Origin':'http://localhost','X-CSRF-Token':self.csrf}).status_code,403)
        with storage.open_db(self.path) as db:
            db.execute("UPDATE users SET role='director' WHERE id=?",(owner,))
        self.assertEqual(self.client.get(f'/api/tournaments/{tid}').status_code,200)
        self.assertEqual(len(self.client.get('/api/tournaments').json['tournaments']),2)

    def test_director_can_still_import_trf(self):
        self.post('/api/users',{'username':'leader','password':'long-password-for-test','role':'director'})
        client=self.app.test_client();csrf=self.login('leader',client)
        preview=self.post('/api/import/preview',self.payload(),client,csrf)
        self.assertEqual(preview.status_code,200,preview.json)
        commit=self.post('/api/import/commit',{'token':preview.json['token']},client,csrf)
        self.assertEqual(commit.status_code,200,commit.json)

    def test_member_code_submission_and_director_approval(self):
        from unittest.mock import patch
        import lichess_import
        self.commit(self.payload())
        invite=self.post('/api/invitations',{}).json['code']
        member=self.app.test_client()
        registration={'code':invite,'username':'member','password':'long-password-for-test','role':'admin'}
        self.assertEqual(self.post('/api/register',registration,member).status_code,200)
        self.assertEqual(self.post('/api/register',{**registration,'username':'second'},member).status_code,400)
        csrf=self.login('member',member)
        self.assertEqual(member.get('/api/me').json['user']['role'],'member')
        for path in ['/api/import/inspect','/api/import/preview','/api/import/commit','/api/lichess/inspect','/api/lichess/preview','/api/invitations']:
            self.assertEqual(self.post(path,{},member,csrf).status_code,403,path)
        players=self.client.get('/api/rankings').json['players'][:2]
        data={'mode':'match','first_player':players[0]['id'],'second_player':players[1]['id'],'first':'Anna','second':'Ben','day':'2025-09-17','consent':True}
        before=[(p['id'],p['rating'],p['games']) for p in self.client.get('/api/rankings').json['players']]
        submitted=self.post('/api/submissions',data,member,csrf)
        self.assertEqual(submitted.status_code,200,submitted.json)
        sid=submitted.json['id']
        self.assertEqual(self.post('/api/submissions',data,member,csrf).status_code,400)
        self.assertEqual([(p['id'],p['rating'],p['games']) for p in self.client.get('/api/rankings').json['players']],before)
        self.assertNotIn('first',member.get('/api/submissions').json['submissions'][0]['payload'])
        item=lichess_import.parse_game({'id':'abcdefgh','variant':'standard','speed':'blitz','status':'mate','winner':'white','lastMoveAt':1758100000000,'players':{'white':{'user':{'name':'Anna'}},'black':{'user':{'name':'Ben'}}}})
        with patch('lichess_import.fetch_match',return_value=[item]):
            checked=self.post('/api/lichess/inspect',{'submission_id':sid})
        self.assertEqual(checked.status_code,200,checked.json)
        self.assertTrue(all(a.get('proposed') for a in checked.json['assignments']))
        preview=self.post('/api/lichess/preview',{'token':checked.json['token'],'consent':True,'selected':['abcdefgh'],'mapping':{'Lichess: Anna':players[0]['id'],'Lichess: Ben':players[1]['id']}})
        self.assertEqual(preview.status_code,200,preview.json)
        self.assertEqual(self.post('/api/import/commit',{'token':preview.json['token']}).status_code,200)
        self.assertEqual(member.get('/api/submissions').json['submissions'][0]['status'],'approved')
        self.assertTrue(all(not t['name'].startswith('Lichess') for t in member.get('/api/tournaments').json['tournaments']))
        second=self.app.test_client()
        self.post('/api/users',{'username':'other','password':'long-password-for-test','role':'member'})
        self.login('other',second)
        self.assertEqual(second.get('/api/submissions').json['submissions'],[])

    def test_member_role_migration_preserves_accounts_and_references(self):
        path=str(Path(self.tmp.name)/'legacy.sqlite')
        with storage.open_db(path) as db:
            db.executescript(storage.SCHEMA.replace("'admin','director','member'","'admin','director'"))
            db.execute("INSERT INTO users VALUES(7,'oldadmin','hash','admin',1,1)")
            db.execute("INSERT INTO sessions VALUES('session',7,'csrf',9999999999)")
            payload={'name':'Vereinsabend','category':'blitz','round_dates':['2025-09-16'],'mapping':{},'text':fixture(),'filename':'old.trf','parsed':trf.parse(fixture())}
            storage.import_tournament(db,payload,7)
        storage.initialize(path)
        with storage.open_db(path) as db:
            self.assertEqual(db.execute('SELECT user_id FROM sessions').fetchone()[0],7)
            self.assertEqual(db.execute('SELECT owner FROM tournaments').fetchone()[0],7)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM games').fetchone()[0],2)
            db.execute("INSERT INTO users VALUES(8,'newmember','hash','member',1,1)")
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
        self.assertTrue(list((Path(path).parent/'backups').glob('before-members-*.sqlite')))

    def test_registration_expiry_and_failed_registration_preserve_code(self):
        code=self.post('/api/invitations',{}).json['code']
        client=self.app.test_client()
        body={'code':code,'username':'admin','password':'long-password-for-test'}
        self.assertEqual(self.post('/api/register',body,client).status_code,409)
        with storage.open_db(self.path) as db:
            self.assertIsNone(db.execute('SELECT used_by FROM invitations').fetchone()[0])
            db.execute('UPDATE invitations SET expires=1')
        self.assertEqual(self.post('/api/register',{**body,'username':'fresh'},client).status_code,400)

    def test_preview_does_not_write_players_or_ratings(self):
        p=self.preview(self.payload())
        self.assertEqual(len(p['tournament']['games']),2)
        self.assertTrue(all(c['before']==1500 for c in p['tournament']['changes']))
        with storage.open_db(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM players').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM tournaments').fetchone()[0],0)
        self.assertEqual(self.client.get('/api/rankings').json['players'],[])

    def test_commit_separation_history_and_duplicate(self):
        tid=self.commit(self.payload())
        blitz=self.client.get('/api/rankings?category=blitz').json['players']
        rapid=self.client.get('/api/rankings?category=rapid').json['players']
        self.assertEqual(len(blitz),4)
        self.assertEqual(sum(p['games'] for p in blitz),4)
        self.assertTrue(all(p['display']==1500 and p['games']==0 for p in rapid))
        self.assertEqual(len(self.client.get(f'/api/tournaments/{tid}').json['changes']),4)
        self.assertEqual(len(self.client.get(f"/api/players/{blitz[0]['id']}").json['history']),1)
        r=self.post('/api/import/preview',self.payload())
        self.assertEqual(r.status_code,400)
        with storage.open_db(self.path) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM players').fetchone()[0],4)

    def test_preview_cannot_be_reused_or_used_by_other_user(self):
        p=self.preview(self.payload())
        self.post('/api/import/commit',{'token':p['token']})
        self.assertEqual(self.post('/api/import/commit',{'token':p['token']}).status_code,400)

    def test_stale_preview_rejected(self):
        a=self.preview(self.payload())
        self.commit(self.payload(category='rapid'))
        self.assertEqual(self.post('/api/import/commit',{'token':a['token']}).status_code,400)

    def test_undo_replay_and_reimport(self):
        tid=self.commit(self.payload())
        self.commit(self.payload(fixture('2025-10-16',draw=True),day='2025-10-16'))
        before=self.client.get('/api/rankings').json['players']
        r=self.post(f'/api/tournaments/{tid}/undo',{'confirm':'Vereinsabend'})
        self.assertEqual(r.status_code,200,r.json)
        after=self.client.get('/api/rankings').json['players']
        self.assertTrue(all(p['games']==1 for p in after))
        self.assertNotEqual([p['display'] for p in before],[p['display'] for p in after])
        self.commit(self.payload())
        final=self.client.get('/api/rankings').json['players']
        self.assertEqual({p['id']:p['rating'] for p in final},{p['id']:p['rating'] for p in before})

    def test_out_of_order_matches_chronological_replay(self):
        later=self.payload(fixture('2025-10-16',draw=True),day='2025-10-16')
        tid=self.commit(later)
        self.commit(self.payload())
        expected={p['id']:p['rating'] for p in self.client.get('/api/rankings').json['players']}
        self.post(f'/api/tournaments/{tid}/undo',{'confirm':'Vereinsabend'})
        self.commit(later)
        self.assertEqual(expected,{p['id']:p['rating'] for p in self.client.get('/api/rankings').json['players']})

    def test_rights_csrf_and_disabled_accounts(self):
        anonymous=self.app.test_client()
        self.assertEqual(anonymous.get('/api/rankings').status_code,401)
        self.assertEqual(self.post('/api/import/inspect',self.payload(),client=anonymous).status_code,401)
        self.assertEqual(self.post('/api/users',{},csrf='wrong').status_code,403)
        self.assertEqual(self.client.post('/api/users',json={},headers={'Origin':'https://evil.test','X-CSRF-Token':self.csrf}).status_code,403)
        self.post('/api/users',{'username':'director','password':'long-password-for-test','role':'director'})
        other=self.app.test_client(); other_csrf=self.login('director',other)
        self.assertEqual(other.get('/api/users').status_code,403)
        tid=self.commit(self.payload())
        self.assertEqual(self.post(f'/api/tournaments/{tid}/undo',{'confirm':'Vereinsabend'},client=other,csrf=other_csrf).status_code,403)
        p=self.preview(self.payload(category='rapid'))
        self.assertEqual(self.post('/api/import/commit',{'token':p['token']},client=other,csrf=other_csrf).status_code,400)
        uid=next(u['id'] for u in self.client.get('/api/users').json['users'] if u['username']=='director')
        self.post(f'/api/users/{uid}',{'active':False})
        self.assertIsNone(other.get('/api/me').json['user'])

    def test_rename_maps_to_existing_player(self):
        self.commit(self.payload())
        original=self.client.get('/api/rankings').json['players']
        anna=next(p for p in original if p['name']=='Alpha, Anna')
        text=fixture('2025-10-16').replace(f"{'Alpha, Anna':33}",f"{'Alpha, A.':33}")
        payload=self.payload(text,day='2025-10-16');payload['mapping']={'1':anna['id']}
        self.commit(payload)
        self.assertEqual(len(self.client.get('/api/rankings').json['players']),4)
        with storage.open_db(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM aliases').fetchone()[0],5)

    def test_same_day_correction_keeps_order(self):
        first=self.commit(self.payload())
        second=self.payload(fixture(draw=True));second['name']='Zweites Turnier'
        self.commit(second)
        expected={p['id']:p['rating'] for p in self.client.get('/api/rankings').json['players']}
        self.post(f'/api/tournaments/{first}/undo',{'confirm':'Vereinsabend'})
        self.commit(self.payload())
        self.assertEqual(expected,{p['id']:p['rating'] for p in self.client.get('/api/rankings').json['players']})

    def test_duplicate_player_mapping_rollback(self):
        self.commit(self.payload())
        first=self.client.get('/api/rankings').json['players'][0]['id']
        payload=self.payload(fixture('2025-10-16').replace(f"{'Alpha, Anna':33}",f"{'New Anna':33}").replace(f"{'Beta, Ben':33}",f"{'New Ben':33}"),day='2025-10-16')
        payload['mapping']={'1':first,'2':first}
        self.assertEqual(self.post('/api/import/preview',payload).status_code,400)
        with storage.open_db(self.path) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM aliases').fetchone()[0],4)

    def test_backup_and_source_exclude_secrets(self):
        self.commit(self.payload())
        backup=backup_database(self.path)
        with closing(sqlite3.connect(backup)) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM players').fetchone()[0],4)
        archive=self.client.get('/source.zip')
        with zipfile.ZipFile(io.BytesIO(archive.data)) as z:
            self.assertIn('app.py',z.namelist())
            self.assertIn('LICENSE',z.namelist())
            self.assertNotIn('.env',z.namelist())
            self.assertFalse(any(n.startswith('data/') or n.endswith('.sqlite') for n in z.namelist()))
        self.assertEqual(self.app.test_client().get('/api/backup').status_code,401)

    def test_bound_member_claim_preserves_profile_and_account(self):
        self.commit(self.payload())
        with storage.open_db(self.path) as db:
            pid=db.execute("SELECT id FROM players WHERE name='Alpha, Anna'").fetchone()[0]
            club_roster.provision(db,[{'name':'Alpha, Anna','club_number':'0001'}])
            uid=db.execute('SELECT user_id FROM club_members WHERE player_id=?',(pid,)).fetchone()[0]
            rating=dict(db.execute('SELECT * FROM ratings WHERE player_id=? LIMIT 1',(pid,)).fetchone())
        anon=self.app.test_client()
        self.assertEqual(self.post('/api/login',{'username':'mitglied-0001','password':'!unclaimed'},client=anon).status_code,401)
        old=self.post('/api/invitations',{'player_id':pid}).json['code']
        new=self.post('/api/invitations',{'player_id':pid}).json['code']
        data={'code':old,'username':'claimed','password':'long-password-for-test'}
        self.assertEqual(self.post('/api/register',data,client=anon).status_code,400)
        data['code']=new
        self.assertEqual(self.post('/api/register',data,client=anon).status_code,200)
        self.assertEqual(self.post('/api/register',data,client=anon).status_code,400)
        with storage.open_db(self.path) as db:
            member=db.execute('SELECT * FROM club_members WHERE player_id=?',(pid,)).fetchone()
            self.assertEqual(member['user_id'],uid)
            self.assertIsNotNone(member['claimed'])
            self.assertEqual(db.execute('SELECT active FROM users WHERE id=?',(uid,)).fetchone()[0],1)
            self.assertEqual(dict(db.execute('SELECT * FROM ratings WHERE player_id=? LIMIT 1',(pid,)).fetchone()),rating)
        self.login('claimed',anon)
        self.assertEqual(anon.get('/api/club-members').status_code,403)

    def test_roster_is_idempotent_and_matches_transliterated_names(self):
        path=Path(self.tmp.name)/'roster.json'
        path.write_text(json.dumps([{'name':'Güler, Selim','club_number':'0001'}]),encoding='utf-8')
        with storage.open_db(self.path) as db:
            pid=db.execute("INSERT INTO players(name,created) VALUES('Gueler, Selim',0)").lastrowid
        club_roster.from_file(path,self.path)
        club_roster.from_file(path,self.path)
        with storage.open_db(self.path) as db:
            self.assertEqual(db.execute('SELECT player_id FROM club_members').fetchone()[0],pid)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM club_members').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM players').fetchone()[0],1)
        self.assertEqual(len(list((Path(self.path).parent/'backups').glob('before-roster-*'))),1)

    def test_entire_site_requires_login(self):
        self.commit(self.payload())
        client = self.app.test_client()
        self.assertIn(b'private-login', client.get('/').data)
        self.assertNotIn(b'ranking-list', client.get('/').data)
        for path in ['/api/rankings', '/api/export.csv', '/api/players/1', '/api/tournaments', '/api/tournaments/1', '/api/users', '/api/audit', '/api/backup', '/source.zip']:
            self.assertEqual(client.get(path).status_code, 401, path)
            self.assertEqual(client.head(path).status_code, 401, path)
        self.assertEqual(client.get('/static/index.html').status_code, 302)
        self.assertEqual(client.get('/api/health').status_code, 200)
        self.login('admin', client)
        self.assertEqual(client.get('/api/rankings').status_code, 200)
        self.assertNotIn(b'private-login', client.get('/').data)

    def test_valid_password_survives_failed_attempts(self):
        anonymous = self.app.test_client()
        for _ in range(11):
            self.post('/api/login', {'username': 'admin', 'password': 'wrong'}, client=anonymous)
        self.assertEqual(self.post('/api/login', {'username': 'admin', 'password': 'long-password-for-test'}, client=anonymous).status_code, 200)

    def test_setup_valid_token_survives_invalid_attempts(self):
        with tempfile.TemporaryDirectory() as folder:
            app = create_app({'DATABASE': str(Path(folder)/'fresh.sqlite'), 'BOOTSTRAP_TOKEN': 'test-bootstrap-key-long-enough-123', 'SECURE_COOKIE': False})
            client = app.test_client()
            for _ in range(11):
                self.post('/api/setup', {'token': 'wrong'}, client=client)
            result = self.post('/api/setup', {'token': 'test-bootstrap-key-long-enough-123', 'username': 'firstadmin', 'password': 'long-password-for-test'}, client=client)
            self.assertEqual(result.status_code, 200)

    def test_public_tournament_hides_login_name(self):
        tid = self.commit(self.payload())
        self.assertNotIn('director', self.app.test_client().get(f'/api/tournaments/{tid}').json)
        self.assertEqual(self.client.get(f'/api/tournaments/{tid}').json['director'], 'admin')

    def test_source_excludes_private_review_document(self):
        with zipfile.ZipFile(io.BytesIO(self.client.get('/source.zip').data)) as archive:
            self.assertNotIn('docs/PRUEFUNG.md', archive.namelist())
            self.assertNotIn('compose.nas-existing-tunnel.yaml', archive.namelist())

    def test_forwarded_ip_is_ignored_without_trusted_proxy(self):
        anonymous = self.app.test_client()
        for i in range(11):
            result = anonymous.post('/api/login', json={'username': 'missing', 'password': 'wrong'}, headers={'Origin': 'http://localhost', 'CF-Connecting-IP': f'192.0.2.{i+1}'})
        self.assertEqual(result.status_code, 429)

    def test_trusted_proxy_separates_clients(self):
        self.app.config['TRUSTED_PROXY_IPS'] = '127.0.0.1'
        anonymous = self.app.test_client()
        for i in range(11):
            result = anonymous.post('/api/login', json={'username': 'missing', 'password': 'wrong'}, headers={'Origin': 'http://localhost', 'CF-Connecting-IP': f'192.0.2.{i+1}'})
            self.assertEqual(result.status_code, 401)

    def test_login_lockout_and_no_second_setup(self):
        anonymous=self.app.test_client()
        for _ in range(10):
            self.assertEqual(self.post('/api/login',{'username':'missing','password':'wrong'},client=anonymous).status_code,401)
        self.assertEqual(self.post('/api/login',{'username':'missing','password':'wrong'},client=anonymous).status_code,429)
        self.assertEqual(self.post('/api/setup',{'token':'test-bootstrap-key-long-enough-123','username':'other','password':'long-password-for-test'}).status_code,400)


if __name__=='__main__':
    unittest.main()
