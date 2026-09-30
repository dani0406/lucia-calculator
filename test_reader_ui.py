"""Exercise independent plate edits and persistence through Streamlit reruns."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from streamlit.testing.v1 import AppTest
from test_reader_plates import fixture_workbook


class ReaderUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        raw = fixture_workbook()
        path = Path(self.temp.name) / 'reader.xlsx'
        path.write_bytes(raw)
        self.key = hashlib.sha256(raw).hexdigest()[:16]
        script = ('from pathlib import Path\nimport lucia_ui\n'
                  f'lucia_ui.EXAMPLE_PATH = Path({str(path)!r})\n'
                  'lucia_ui.render_lucia()\n')
        self.app = AppTest.from_string(script).run(timeout=20)

    def prefix(self, group):
        return f'{self.key}:{group}:Raw reader {group}:F'

    def test_independent_plate_assignments_remove_undo_and_slider_persistence(self):
        app = self.app
        a, b = self.prefix('A'), self.prefix('B')
        app.multiselect(key=a + ':selected').set_value(['F1', 'F2', 'F3', 'F4']).run()
        app.radio(key=a + ':mode').set_value('Series in well order').run()
        app.text_input(key=a + ':name').set_value('My A protein').run()
        app.button(key=a + ':assign').click().run()
        self.assertEqual(len(app.session_state[a + ':layout']), 4)
        self.assertEqual(app.session_state[b + ':layout'], {})
        app.button(key=b + ':preset').click().run()
        self.assertEqual(len(app.session_state[b + ':layout']), 18)
        app.slider[0].set_value(50).run()
        self.assertEqual(len(app.error), 1)
        self.assertEqual(len(app.session_state[a + ':layout']), 4)
        app.button(key=a + ':remove').click().run()
        self.assertEqual(app.session_state[a + ':layout'], {})
        self.assertEqual(len(app.session_state[b + ':layout']), 18)
        app.button(key=a + ':undo_button').click().run()
        self.assertEqual(len(app.session_state[a + ':layout']), 4)
        self.assertFalse(app.exception)

    def test_invalid_series_does_not_overwrite_and_changed_column_is_separate(self):
        app = self.app
        a = self.prefix('A')
        app.button(key=a + ':preset').click().run()
        original = dict(app.session_state[a + ':layout'])
        app.multiselect(key=a + ':selected').set_value(['F1', 'F2']).run()
        app.radio(key=a + ':mode').set_value('Series in well order').run()
        app.button(key=a + ':assign').click().run()
        self.assertEqual(app.session_state[a + ':layout'], original)
        self.assertTrue(any('one calibration volume' in error.value for error in app.error))
        app.selectbox(key=self.key + ':a_column').set_value('G').run()
        self.assertEqual(app.session_state[a.replace(':F', ':G') + ':layout'], {})
        app.selectbox(key=self.key + ':a_column').set_value('F').run()
        self.assertEqual(app.session_state[a + ':layout'], original)
        self.assertFalse(app.exception)


if __name__ == '__main__':
    unittest.main()
