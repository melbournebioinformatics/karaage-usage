# Copyright 2007-2014 VPAC
#
# This file is part of Karaage.
#
# Karaage is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Karaage is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Karaage  If not, see <http://www.gnu.org/licenses/>.

import mock
from django.test import TestCase
from django.core import mail
from django.core.urlresolvers import reverse
from django.conf import settings
from django.core.management import call_command

from karaage.people.models import Group
from karaage.applications.models import Application
from karaage.tests.unit import UnitTestCase
from karaage.tests.fixtures import GroupFactory, simple_account

from kgusage.usage_software.models import Software, SoftwareLicense
from kgusage.usage_software.models import SoftwareApplication

from .fixtures import SoftwareFactory


class SoftwareTestCase(UnitTestCase):

    def test_change_group(self):
        """Check that when changing an software group, old accounts are
        removed from the software and new ones are added.

        """
        account1 = simple_account(machine_category=self.machine_category)
        group1 = GroupFactory()
        group1.add_person(account1.person)

        # Test during initial creation of the software
        self.resetDatastore()
        software = SoftwareFactory(group=group1)
        self.assertEqual(
            self.datastore.method_calls,
            [mock.call.save_software(software),
                mock.call.add_account_to_software(account1, software)])

        # Test changing an existing software group
        account2 = simple_account(machine_category=self.machine_category)
        self.resetDatastore()
        group2 = GroupFactory()
        group2.add_person(account2.person)
        software.group = group2
        software.save()
        self.assertEqual(
            self.datastore.method_calls,
            [mock.call.save_group(group2),
             mock.call.add_account_to_group(account2, group2),
             mock.call.save_software(software),
             # old accounts are removed
             mock.call.remove_account_from_software(account1, software),
             # new accounts are added
             mock.call.add_account_to_software(account2, software)])

        # Test removing the group
        #
        # Test is currently broken, as the save() operation will give the
        # software a group if none is given. This will be fixed in
        # https://code.vpac.org/gerrit/#/c/852/
        #
        # self.resetDatastore()
        # software.group = None
        # software.save()
        # self.assertEqual(
        #    self.datastore.method_calls,
        #    [mock.call.save_software(software),
        #     # old accounts are removed
        #     mock.call.remove_account_from_software(account2, software)])


def set_admin():
    settings.ADMIN_IGNORED = False


def set_no_admin():
    settings.ADMIN_IGNORED = True


class SoftwareApplicationTestCase(TestCase):

    def setUp(self):
        call_command('loaddata', 'karaage_data', **{'verbosity': 0})

    def tearDown(self):
        set_admin()

    def test_register_software(self):
        group = Group.objects.create(name="windows")
        software = Software.objects.create(
            name="windows",
            restricted=True,
            group=group,
        )
        SoftwareLicense.objects.create(
            software=software,
            version="3.11",
            text="You give your soal to the author "
            "if you wish to access this software.",
        )

        set_no_admin()

        # APPLICANT LOGS IN
        logged_in = self.client.login(
            username='kgtestuser1', password='aq12ws')
        self.assertEqual(logged_in, True)
        self.assertEqual(len(mail.outbox), 0)

        response = self.client.get(
            reverse('kg_software_detail', args=[software.pk]))
        self.assertEqual(response.status_code, 200)

        # OPEN APPLICATION
        form_data = {
        }

        response = self.client.post(
            reverse('kg_software_detail', args=[software.pk]),
            form_data, follow=True)
        self.assertEqual(response.status_code, 200)
        application = Application.objects.get()
        self.assertEqual(
            response.redirect_chain[0][0],
            'http://testserver'
            + reverse('kg_application_detail', args=[application.pk, 'O']))
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(
            mail.outbox[0].subject.startswith('TestOrg invitation'))
        self.assertEqual(mail.outbox[0].from_email, settings.ACCOUNTS_EMAIL)
        self.assertEqual(mail.outbox[0].to[0], 'leader@example.com')

        # SUBMIT APPLICATION
        form_data = {
            'submit': True,
        }

        response = self.client.post(
            reverse('kg_application_detail', args=[application.pk, 'O']),
            form_data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.redirect_chain[0][0],
            'http://testserver'
            + reverse('kg_application_detail', args=[application.pk, 'K']))

        self.assertEqual(len(mail.outbox), 2)
        self.assertTrue(
            mail.outbox[1].subject == 'TestOrg request for access to windows')
        self.assertEqual(mail.outbox[1].from_email, settings.ACCOUNTS_EMAIL)
        self.assertEqual(mail.outbox[1].to[0], 'sam@vpac.org')

        # ADMIN LOGS IN TO APPROVE
        set_admin()
        logged_in = self.client.login(username='kgsuper', password='aq12ws')
        self.assertEqual(logged_in, True)

        # ADMIN GET DETAILS
        response = self.client.get(
            reverse('kg_application_detail', args=[application.pk, 'K']))
        self.assertEqual(response.status_code, 200)

        # ADMIN GET DECLINE PAGE
        response = self.client.get(
            reverse('kg_application_detail',
                    args=[application.pk, 'K', 'decline']))
        self.assertEqual(response.status_code, 200)

        # ADMIN GET APPROVE PAGE
        response = self.client.get(
            reverse('kg_application_detail',
                    args=[application.pk, 'K', 'approve']))
        self.assertEqual(response.status_code, 200)

        # ADMIN APPROVE
        form_data = {
            'make_leader': False,
            'additional_req': 'Woof',
            'needs_account': False,
        }
        response = self.client.post(
            reverse('kg_application_detail',
                    args=[application.pk, 'K', 'approve']),
            form_data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.redirect_chain[0][0],
            'http://testserver'
            + reverse('kg_application_detail', args=[application.pk, 'C']))
        application = Application.objects.get(pk=application.id)
        self.assertEqual(application.state, SoftwareApplication.COMPLETED)
        self.assertEqual(len(mail.outbox), 3)
        self.assertEqual(mail.outbox[2].from_email, settings.ACCOUNTS_EMAIL)
        self.assertEqual(mail.outbox[2].to[0], 'leader@example.com')
        self.client.logout()
        set_no_admin()

        # test group
        groups = Group.objects.filter(
            name="windows", members__username="kgtestuser1")
        self.assertEqual(len(groups), 1)