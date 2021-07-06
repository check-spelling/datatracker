# Copyright The IETF Trust 2021 All Rights Reserved

import debug    # pyflakes:ignore
import io
import shutil
import os

from pyquery import PyQuery
from tempfile import NamedTemporaryFile

from django.conf import settings
from django.urls import reverse as urlreverse

from ietf.doc.factories import BofreqFactory, NewRevisionDocEventFactory
from ietf.doc.models import State, BofreqEditorDocEvent, Document, DocAlias, NewRevisionDocEvent
from ietf.person.factories import PersonFactory
from ietf.utils.mail import outbox, empty_outbox
from ietf.utils.test_utils import TestCase, reload_db_objects, unicontent, login_testing_unauthorized



class BofreqTests(TestCase):

    def setUp(self):
        self.bofreq_dir = self.tempdir('bofreq')
        self.saved_bofreq_path = settings.BOFREQ_PATH
        settings.BOFREQ_PATH = self.bofreq_dir

    def tearDown(self):
        settings.BOFREQ_PATH = self.saved_bofreq_path
        shutil.rmtree(self.bofreq_dir)

    def write_bofreq_file(self, bofreq):
        fname = os.path.join(self.bofreq_dir, "%s-%s.md" % (bofreq.canonical_name(), bofreq.rev))
        with io.open(fname, "w") as f:
            f.write(f"""# This is a test bofreq.
Version: {bofreq.rev}

## A section

This test section has some text.
""")

    def test_show_bof_requests(self):
        states = State.objects.filter(type_id='bofreq')
        self.assertTrue(states.count()>0)
        reqs = BofreqFactory.create_batch(states.count())
        url = urlreverse('ietf.doc.views_bofreq.bof_requests')
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        q = PyQuery(r.content)
        self.assertEqual(len(q('#bofreqs-proposed tbody tr')), states.count())
        for i in range(states.count()):
            reqs[i].set_state(states[i])
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        q = PyQuery(r.content)
        for state in states:
            self.assertEqual(len(q(f'#bofreqs-{state.slug} tbody tr')), 1)


    def test_bofreq_main_page(self):
        doc = BofreqFactory()
        doc.save_with_history(doc.docevent_set.all())
        self.write_bofreq_file(doc)
        nr_event = NewRevisionDocEventFactory(doc=doc,rev='01')
        doc.rev='01'
        doc.save_with_history([nr_event])
        self.write_bofreq_file(doc)
        editors = doc.latest_event(BofreqEditorDocEvent).editors.all()
        url = urlreverse('ietf.doc.views_doc.document_main', kwargs=dict(name=doc))
        r = self.client.get(url)
        self.assertContains(r,'Version: 01',status_code=200)
        q = PyQuery(r.content)
        self.assertEqual(0, len(q('td.edit>a.btn')))
        self.assertEqual([],q('#change-request'))
        editor_row = q('#editors').html()
        for editor in editors:
            self.assertInHTML(editor.plain_name(),editor_row)
        for user in ('secretary','ad','iab-member'): 
            self.client.login(username=user,password=user+"+password")
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            q = PyQuery(r.content)
            self.assertEqual(4, len(q('td.edit>a.btn')))
            self.client.logout()
            self.assertNotEqual([],q('#change-request'))
        editor = editors.first().user.username
        self.client.login(username=editor, password=editor+"+password")
        r = self.client.get(url)
        self.assertEqual(r.status_code,200)
        q = PyQuery(r.content)
        self.assertEqual(2, len(q('td.edit>a.btn')))
        self.assertNotEqual([],q('#change-request'))
        self.client.logout()
        url = urlreverse('ietf.doc.views_doc.document_main', kwargs=dict(name=doc,rev='00'))
        r = self.client.get(url)
        self.assertContains(r,'Version: 00',status_code=200)
        self.assertContains(r,'is for an older version')

    def test_edit_title(self):
        doc = BofreqFactory()
        editor = doc.latest_event(BofreqEditorDocEvent).editors.first()
        url = urlreverse('ietf.doc.views_bofreq.edit_title', kwargs=dict(name=doc.name))
        title = doc.title
        r = self.client.post(url,dict(title='New title'))
        self.assertEqual(r.status_code, 302)
        doc = reload_db_objects(doc)
        self.assertEqual(title, doc.title)
        nobody = PersonFactory()
        self.client.login(username=nobody.user.username,password=nobody.user.username+'+password')
        r = self.client.post(url,dict(title='New title'))
        self.assertEqual(r.status_code, 403)
        doc = reload_db_objects(doc)
        self.assertEqual(title, doc.title)
        self.client.logout()
        for username in ('secretary', 'ad', 'iab-member', editor.user.username):
            self.client.login(username=username, password=username+'+password')
            r = self.client.get(url)
            self.assertEqual(r.status_code,200)
            docevent_count = doc.docevent_set.count()
            empty_outbox()
            r = self.client.post(url,dict(title=username))
            self.assertEqual(r.status_code,302)
            doc = reload_db_objects(doc)
            self.assertEqual(doc.title, username)
            self.assertEqual(docevent_count+1, doc.docevent_set.count())
            self.assertEqual(1, len(outbox)) 
            self.client.logout()

    def state_pk_as_str(self, type_id, slug):
        return str(State.objects.get(type_id=type_id, slug=slug).pk)

    def test_edit_state(self):
        doc = BofreqFactory()
        editor = doc.latest_event(BofreqEditorDocEvent).editors.first()
        url = urlreverse('ietf.doc.views_bofreq.change_state', kwargs=dict(name=doc.name))
        state = doc.get_state('bofreq')
        r = self.client.post(url, dict(new_state=self.state_pk_as_str('bofreq','approved')))
        self.assertEqual(r.status_code, 302)
        doc = reload_db_objects(doc)
        self.assertEqual(state, doc.get_state('bofreq'))
        self.client.login(username=editor.user.username,password=editor.user.username+'+password')
        r = self.client.post(url, dict(new_state=self.state_pk_as_str('bofreq','approved')))
        self.assertEqual(r.status_code, 403)
        doc = reload_db_objects(doc)
        self.assertEqual(state,doc.get_state('bofreq'))
        self.client.logout()
        for username in ('secretary', 'ad', 'iab-member'):
            doc.set_state(state)
            self.client.login(username=username,password=username+'+password')
            r = self.client.get(url)
            self.assertEqual(r.status_code,200)
            docevent_count = doc.docevent_set.count()
            r = self.client.post(url,dict(new_state=self.state_pk_as_str('bofreq','approved' if username=='secretary' else 'declined'),comment=f'{username}-2309hnf'))
            self.assertEqual(r.status_code,302)
            doc = reload_db_objects(doc)
            self.assertEqual('approved' if username=='secretary' else 'declined',doc.get_state_slug('bofreq'))
            self.assertEqual(docevent_count+2, doc.docevent_set.count())
            self.assertIn(f'{username}-2309hnf',doc.latest_event(type='added_comment').desc)
            self.client.logout()

    def test_change_editors(self):
        doc = BofreqFactory()
        previous_editors = list(doc.latest_event(BofreqEditorDocEvent).editors.all())
        acting_editor = previous_editors[0]
        new_editors = set(previous_editors)
        new_editors.discard(acting_editor)
        new_editors.add(PersonFactory())
        url = urlreverse('ietf.doc.views_bofreq.change_editors', kwargs=dict(name=doc.name))
        postdict = dict(editors=','.join([str(p.pk) for p in new_editors]))
        r = self.client.post(url, postdict)
        self.assertEqual(r.status_code,302)
        editors = doc.latest_event(BofreqEditorDocEvent).editors.all()
        self.assertEqual(set(previous_editors),set(editors))
        nobody = PersonFactory()
        self.client.login(username=nobody.user.username,password=nobody.user.username+'+password')
        r = self.client.post(url, postdict)
        self.assertEqual(r.status_code,403)
        editors = doc.latest_event(BofreqEditorDocEvent).editors.all()
        self.assertEqual(set(previous_editors),set(editors))
        self.client.logout()
        for username in (previous_editors[0].user.username, 'secretary', 'ad', 'iab-member'):
            empty_outbox()
            self.client.login(username=username,password=username+'+password')
            r = self.client.get(url)
            self.assertEqual(r.status_code,200)
            for editor in previous_editors:
                unescaped = unicontent(r).encode('utf-8').decode('unicode-escape')
                self.assertIn(editor.name,unescaped)
            new_editors = set(previous_editors)
            new_editors.discard(acting_editor)
            new_editors.add(PersonFactory())
            postdict = dict(editors=','.join([str(p.pk) for p in new_editors]))
            r = self.client.post(url,postdict)
            self.assertEqual(r.status_code, 302)
            updated_editors = doc.latest_event(BofreqEditorDocEvent).editors.all()
            self.assertEqual(new_editors,set(updated_editors))
            previous_editors = new_editors
            self.client.logout()
            self.assertEqual(len(outbox),1)
            self.assertIn('BOF Request editors changed',outbox[0]['Subject'])

    def test_submit(self):
        doc = BofreqFactory()
        url = urlreverse('ietf.doc.views_bofreq.submit', kwargs=dict(name=doc.name))

        rev = doc.rev
        r = self.client.post(url,{'bofreq_submission':'enter','bofreq_content':'# oiwefrase'})
        self.assertEqual(r.status_code, 302)
        doc = reload_db_objects(doc)
        self.assertEqual(rev, doc.rev)

        nobody = PersonFactory()
        self.client.login(username=nobody.user.username, password=nobody.user.username+'+password')
        r = self.client.post(url,{'bofreq_submission':'enter','bofreq_content':'# oiwefrase'})
        self.assertEqual(r.status_code, 403)
        doc = reload_db_objects(doc)
        self.assertEqual(rev, doc.rev)
        self.client.logout()

        editor = doc.latest_event(BofreqEditorDocEvent).editors.first()
        for username in ('secretary', 'ad', 'iab-member', editor.user.username):
            self.client.login(username=username, password=username+'+password')
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            file = NamedTemporaryFile(delete=False,mode="w+",encoding='utf-8')
            file.write(f'# {username}')
            file.close()
            for postdict in [
                        {'bofreq_submission':'enter','bofreq_content':f'# {username}'},
                        {'bofreq_submission':'upload','bofreq_file':open(file.name,'rb')},
                     ]:
                docevent_count = doc.docevent_set.count()
                empty_outbox()
                r = self.client.post(url, postdict)
                self.assertEqual(r.status_code, 302)
                doc = reload_db_objects(doc)
                self.assertEqual('%02d'%(int(rev)+1) ,doc.rev)
                self.assertEqual(f'# {username}', doc.text())
                self.assertEqual(docevent_count+1, doc.docevent_set.count())
                self.assertEqual(1, len(outbox))
                rev = doc.rev
            self.client.logout()
            os.unlink(file.name)

    def test_start_new_bofreq(self):
        url = urlreverse('ietf.doc.views_bofreq.new_bof_request')
        nobody = PersonFactory()
        login_testing_unauthorized(self,nobody.user.username,url)
        r = self.client.get(url)
        self.assertContains(r,'Fill in the details below. Keep items in the order they appear here.',status_code=200)
        file = NamedTemporaryFile(delete=False,mode="w+",encoding='utf-8')
        file.write('some stuff')
        file.close()
        for postdict in [
                            dict(title='title one', bofreq_submission='enter', bofreq_content='some stuff'),
                            dict(title='title two', bofreq_submission='upload', bofreq_file=open(file.name,'rb')),
                        ]:
            empty_outbox()
            r = self.client.post(url, postdict)
            self.assertEqual(r.status_code,302)
            name = f"bofreq-{postdict['title']}".replace(' ','-')
            bofreq = Document.objects.filter(name=name,type_id='bofreq').first()
            self.assertIsNotNone(bofreq)
            self.assertIsNotNone(DocAlias.objects.filter(name=name).first())
            self.assertEqual(bofreq.title, postdict['title'])
            self.assertEqual(bofreq.rev, '00')
            self.assertEqual(bofreq.get_state_slug(), 'proposed')
            self.assertEqual(list(bofreq.latest_event(BofreqEditorDocEvent).editors.all()), [nobody])
            self.assertEqual(bofreq.latest_event(NewRevisionDocEvent).rev, '00')
            self.assertEqual(bofreq.text_or_error(), 'some stuff')
            self.assertEqual(len(outbox),1)
        os.unlink(file.name)
        existing_bofreq = BofreqFactory()
        for postdict in [
                            dict(title='', bofreq_submission='enter', bofreq_content='some stuff'),
                            dict(title='a title', bofreq_submission='enter', bofreq_content=''),
                            dict(title=existing_bofreq.title, bofreq_submission='enter', bofreq_content='some stuff'),
                            dict(title='森川', bofreq_submission='enter', bofreq_content='some stuff'),
                            dict(title='a title', bofreq_submission='', bofreq_content='some stuff'),
                        ]:
            r = self.client.post(url,postdict)
            self.assertEqual(r.status_code, 200)
            q = PyQuery(r.content)
            self.assertTrue(q('form div.has-error'))
