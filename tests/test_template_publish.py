"""New template page publishing creates only after validation and cleans up failures."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
import kf_sections as sections

class TemplatePublishTests(unittest.TestCase):
    def test_new_page_is_verified_before_publish(self):
        blocks=[{'type':'hero','title':'Portfolio','text':'Work and projects','kicker':'Studio'},
                {'type':'cards','title':'Projects','items':[{'title':'Project','text':'Verified project details'}]}]
        html=sections.render_sections(blocks)
        self.assertGreater(len(html),sections.MIN_HTML)
        for failure in ('none','content','publish'):
            with self.subTest(failure=failure):
                calls=[]
                def wp(site,*args,stdin=None):
                    calls.append((args,stdin))
                    if args[:2]==('post','create'):
                        self.assertIn('--post_status=draft',args)
                        return SimpleNamespace(returncode=0,stdout='42\n',stderr='')
                    return SimpleNamespace(returncode=int(failure=='publish' and args[:2]==('post','update')),stdout='',stderr='')
                with patch.object(sections,'page_id',return_value=None),patch.object(sections,'get_content',return_value='bad' if failure=='content' else html),patch.object(sections,'wp',side_effect=wp):
                    result=sections.save_page('/unused','portfolio',blocks,'Portfolio')
                self.assertEqual(result['ok'],failure=='none')
                commands=[args for args,_ in calls]
                if failure=='none':self.assertEqual(commands[-1],('post','update','42','--post_status=publish'))
                else:self.assertEqual(commands[-1],('post','delete','42','--force'));self.assertTrue(result['rolled_back'])
                if failure=='content':self.assertFalse(any(args[:2]==('post','update') for args in commands))
