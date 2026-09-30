"""Exercise independent plate edits and persistence through Streamlit reruns."""
from copy import deepcopy
import csv
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from openpyxl import load_workbook
from streamlit.testing.v1 import AppTest
from test_reader_plates import fixture_workbook


def many_proteins_workbook():
    """Three A groups and twelve B groups, all independent measured series."""
    workbook = load_workbook(io.BytesIO(fixture_workbook()))
    a, b = workbook['Raw reader A'], workbook['Raw reader B']
    for index in range(12):
        dose = (1, .5, .25, .125)[index % 4]
        a.cell(40 + index, 1, f'F{index + 1}')
        a.cell(40 + index, 6, dose * 100_000_000 / 20)
    for index in range(36):
        dose = (.01, .001, .0001)[index % 3]
        b.cell(40 + index, 1, f'{chr(ord("B") + index // 12)}{index % 12 + 1}')
        b.cell(40 + index, 6, dose * 400_000_000 / .5)
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


class ReaderUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.load_app(fixture_workbook())

    def load_app(self, raw, capture_downloads=False):
        path = Path(self.temp.name) / 'reader.xlsx'
        path.write_bytes(raw)
        self.key = hashlib.sha256(raw).hexdigest()[:16]
        script = ('from pathlib import Path\nimport lucia_ui\n'
                  f'lucia_ui.EXAMPLE_PATH = Path({str(path)!r})\n')
        if capture_downloads:
            script += ('from unittest.mock import patch\n'
                       'import streamlit as st\n'
                       'real_download = st.download_button\n'
                       'st.session_state["test_downloads"] = {}\n'
                       'def capture_download(label, data, *args, **kwargs):\n'
                       '    st.session_state["test_downloads"][label] = data\n'
                       '    return real_download(label, data, *args, **kwargs)\n'
                       'with patch("streamlit.download_button", side_effect=capture_download):\n'
                       '    lucia_ui.render_lucia()\n')
        else:
            script += 'lucia_ui.render_lucia()\n'
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

    def test_named_b_group_becomes_assignable_and_survives_reader_rename(self):
        app = self.app
        b = self.prefix('B')
        destination = self.key + ':destination'
        plate = destination + ':plate-1'
        app.radio(key=plate + ':layer').set_value('B overlay').run()
        app.text_input(key=b + ':name').set_value('Named B protein').run()
        self.assertEqual(app.selectbox(key=plate + ':B:protein').options,
                         ['Keep current assignment', 'Clear this layer'])
        self.assertEqual(app.session_state[b + ':layout'], {})

        app.multiselect(key=b + ':selected').set_value(['B1', 'B2', 'B3']).run()
        app.radio(key=b + ':mode').set_value('Series in well order').run()
        app.button(key=b + ':assign').click().run()
        self.assertIn('Named B protein (B1)', app.selectbox(key=plate + ':B:protein').options)
        app.multiselect(key=plate + ':selected').set_value(['A1', 'A2']).run()
        app.selectbox(key=plate + ':B:protein').set_value('protein:B1').run()
        app.text_input(key=plate + ':label').set_value('Destination note').run()
        app.radio(key=plate + ':layer').set_value('A protein or mCherry').run()

        app.text_input(key=b + ':name').set_value('Renamed B protein').run()
        app.button(key=b + ':assign').click().run()
        app.radio(key=plate + ':layer').set_value('B overlay').run()
        self.assertEqual(app.selectbox(key=plate + ':B:protein').value, 'protein:B1')
        self.assertIn('Renamed B protein (B1)', app.selectbox(key=plate + ':B:protein').options)
        self.assertEqual(app.multiselect(key=plate + ':selected').value, ['A1', 'A2'])
        self.assertEqual(app.text_input(key=plate + ':label').value, 'Destination note')
        self.assertEqual(app.session_state[destination + ':layouts']['plate-1']['wells'], {})
        app.button(key=plate + ':assign').click().run()
        wells = app.session_state[destination + ':layouts']['plate-1']['wells']
        self.assertEqual(set(wells), {'A1', 'A2'})
        self.assertTrue(all(well['b_protein_id'] == 'B1' for well in wells.values()))
        self.assertTrue(all(well['label'] == 'Destination note' for well in wells.values()))
        self.assertFalse(app.exception)

    def test_more_than_six_b_groups_optional_reader_names_and_exports(self):
        self.load_app(many_proteins_workbook(), capture_downloads=True)
        app = self.app
        a, b = self.prefix('A'), self.prefix('B')
        destination = self.key + ':destination'
        plate = destination + ':plate-1'
        app.button(key=a + ':preset').click().run()
        app.button(key=b + ':preset').click().run()
        initial_a = deepcopy(app.session_state[a + ':layout'])
        initial_b = deepcopy(app.session_state[b + ':layout'])

        # The same optional-name workflow works on reader A beyond A1/A2.
        app.multiselect(key=a + ':selected').set_value(['F1']).run()
        app.text_input(key=a + ':name').set_value('An unsaved name').run()
        app.button(key=a + ':new_protein').click().run()
        self.assertEqual(app.text_input(key=a + ':protein').value, 'A3')
        self.assertEqual(app.text_input(key=a + ':name').value, '')
        self.assertEqual(app.multiselect(key=a + ':selected').value, [])
        self.assertEqual(app.session_state[a + ':layout'], initial_a)
        app.multiselect(key=a + ':selected').set_value(['F9', 'F10', 'F11', 'F12']).run()
        app.radio(key=a + ':mode').set_value('Series in well order').run()
        app.text_input(key=a + ':name').set_value('Custom A three').run()
        app.button(key=a + ':assign').click().run()
        self.assertIn('Custom A three (A3)', app.selectbox(key=plate + ':A:protein').options)

        # Add six further B groups through the real reader controls, rather
        # than preloading assignments and bypassing the new-protein action.
        app.radio(key=b + ':mode').set_value('Series in well order').run()
        app.radio(key=plate + ':layer').set_value('B overlay').run()
        for number in range(7, 13):
            with self.subTest(protein=f'B{number}'):
                previous = deepcopy(app.session_state[b + ':layout'])
                app.button(key=b + ':new_protein').click().run()
                self.assertEqual(app.text_input(key=b + ':protein').value, f'B{number}')
                self.assertEqual(app.text_input(key=b + ':name').value, '')
                self.assertEqual(app.multiselect(key=b + ':selected').value, [])
                self.assertEqual(app.session_state[b + ':layout'], previous)
                indices = range((number - 1) * 3, number * 3)
                wells = [f'{chr(ord("B") + index // 12)}{index % 12 + 1}' for index in indices]
                app.multiselect(key=b + ':selected').set_value(wells).run()
                if number == 7:
                    app.text_input(key=b + ':name').set_value('Custom binder seven').run()
                app.button(key=b + ':assign').click().run()
                expected_name = 'Custom binder seven' if number == 7 else f'B{number}'
                for well in wells:
                    self.assertEqual(app.session_state[b + ':layout'][well]['protein_id'], f'B{number}')
                    self.assertEqual(app.session_state[b + ':layout'][well]['protein_name'], expected_name)
        saved_b = app.session_state[b + ':layout']
        self.assertEqual({well: saved_b[well] for well in initial_b}, initial_b)
        self.assertEqual(len({item['protein_id'] for item in saved_b.values()}), 12)
        self.assertIn('Custom binder seven (B7)', app.selectbox(key=plate + ':B:protein').options)
        self.assertIn('B12', app.selectbox(key=plate + ':B:protein').options)

        app.radio(key=plate + ':layer').set_value('A protein or mCherry').run()
        app.multiselect(key=plate + ':selected').set_value(['H1', 'H2']).run()
        app.selectbox(key=plate + ':A:protein').set_value('protein:A3').run()
        app.button(key=plate + ':assign').click().run()
        app.radio(key=plate + ':layer').set_value('B overlay').run()
        for well, identity in [('H1', 'B7'), ('H2', 'B12')]:
            app.multiselect(key=plate + ':selected').set_value([well]).run()
            app.selectbox(key=plate + ':B:protein').set_value('protein:' + identity).run()
            app.button(key=plate + ':assign').click().run()

        downloads = app.session_state['test_downloads']
        record = json.loads(downloads['Download calculation record and plate layouts'])
        proteins = {(protein['group'], protein['protein_id']): protein for protein in record['proteins']}
        self.assertEqual(len(proteins), 15)
        self.assertEqual(proteins['A', 'A1']['protein_name'], 'A1')
        self.assertEqual(proteins['A', 'A3']['protein_name'], 'Custom A three')
        self.assertEqual(proteins['B', 'B7']['protein_name'], 'Custom binder seven')
        self.assertEqual(proteins['B', 'B12']['protein_name'], 'B12')
        wells = record['lucia_plates']['plate-1']['wells']
        self.assertEqual(wells['H1']['a_protein_id'], 'A3')
        self.assertEqual(wells['H1']['b_protein_id'], 'B7')
        self.assertEqual(wells['H2']['b_protein_id'], 'B12')
        transfers = {(row['well'], row['stage']): row for row in record['destination_preview']['transfers']}
        self.assertTrue(record['destination_preview']['ready'])
        self.assertEqual(transfers['H1', 'B']['protein_name'], 'Custom binder seven')
        self.assertEqual(transfers['H2', 'B']['protein_name'], 'B12')
        layout = json.loads(downloads['Save LUCIA plate layout'])
        self.assertEqual(layout['protein_names']['A']['A3'], 'Custom A three')
        self.assertEqual(layout['protein_names']['B']['B7'], 'Custom binder seven')
        self.assertEqual(layout['protein_names']['B']['B12'], 'B12')
        csv_rows = {row['protein_id']: row for row in csv.DictReader(io.StringIO(downloads['Download calculation CSV']))}
        self.assertEqual(csv_rows['A3']['protein_name'], 'Custom A three')
        self.assertEqual(csv_rows['B7']['protein_name'], 'Custom binder seven')
        self.assertEqual(csv_rows['B12']['protein_name'], 'B12')
        self.assertFalse(app.exception)


if __name__ == '__main__':
    unittest.main()
