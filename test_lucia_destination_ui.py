"""Exercise independent layers, plate state, manual edits and saved drafts."""
from copy import deepcopy
import json
import unittest

from streamlit.testing.v1 import AppTest

from lucia_destination import create_plate, protein_catalog
from lucia_destination_ui import (apply_destination_table, destination_figure,
                                   destination_table_rows, restore_destination_layout)
from test_lucia_destination import calculation_report


class DestinationUITests(unittest.TestCase):
    def setUp(self):
        self.app = AppTest.from_string(
            'import streamlit as st\n'
            'from test_lucia_destination import calculation_report\n'
            'from lucia_destination_ui import render_destination_planner\n'
            'report = st.session_state.get("report_override", calculation_report())\n'
            'render_destination_planner(report, "test")\n').run(timeout=20)
        self.prefix = 'test:destination'
        self.plate = self.prefix + ':plate-1'

    def assign(self, group, identity, wells):
        app = self.app
        layer = 'A protein or mCherry' if group == 'A' else 'B overlay'
        app.radio(key=self.plate + ':layer').set_value(layer).run()
        app.multiselect(key=self.plate + ':selected').set_value(wells).run()
        app.selectbox(key=self.plate + f':{group}:protein').set_value(identity).run()
        app.button(key=self.plate + ':assign').click().run()

    def test_layers_multiple_a_proteins_mcherry_and_independent_plates(self):
        app = self.app
        self.assign('A', 'protein:A1', ['A1', 'A2'])
        self.assign('A', 'protein:A2', ['A3'])
        self.assign('A', 'mcherry', ['A4'])
        self.assign('B', 'protein:B1', ['A1', 'A2', 'A3', 'A4'])
        first = deepcopy(app.session_state[self.prefix + ':layouts']['plate-1'])
        self.assertEqual(first['wells']['A1']['a_protein_id'], 'A1')
        self.assertEqual(first['wells']['A3']['a_protein_id'], 'A2')
        self.assertEqual(first['wells']['A4']['a_control'], 'mCherry')
        self.assertTrue(all(item['b_protein_id'] == 'B1' for item in first['wells'].values()))
        app.button(key=self.prefix + ':add').click().run()
        self.assertEqual(app.session_state[self.prefix + ':active'], 'plate-2')
        self.assertEqual(app.session_state[self.prefix + ':layouts']['plate-2']['wells'], {})
        self.assertEqual(app.session_state[self.prefix + ':layouts']['plate-1'], first)
        app.button(key=self.prefix + ':delete').click().run()
        self.assertEqual(list(app.session_state[self.prefix + ':layouts']), ['plate-1'])
        app.button(key=self.prefix + ':undo_button').click().run()
        self.assertEqual(list(app.session_state[self.prefix + ':layouts']), ['plate-1', 'plate-2'])
        self.assertFalse(app.exception)

    def test_plate_rename_and_navigation_preserve_each_pending_form(self):
        app = self.app
        app.radio(key=self.plate + ':layer').set_value('B overlay').run()
        app.selectbox(key=self.plate + ':B:protein').set_value('protein:B1').run()
        app.multiselect(key=self.plate + ':selected').set_value(['H3']).run()
        app.text_input(key=self.plate + ':label').set_value('First plate note').run()
        app.radio(key=self.plate + ':selection_tool').set_value('Lasso').run()
        app.button(key=self.prefix + ':add').click().run()
        second = self.prefix + ':plate-2'
        app.selectbox(key=second + ':A:protein').set_value('protein:A2').run()
        app.multiselect(key=second + ':selected').set_value(['G2']).run()
        app.text_input(key=second + ':label').set_value('Second plate note').run()
        revision = app.session_state[self.prefix + ':revision']
        app.text_input(key=second + f':rename:{revision}').set_value('Renamed second plate').run()
        app.button(key=self.prefix + ':rename').click().run()
        self.assertEqual(app.session_state[self.prefix + ':active'], 'plate-2')
        self.assertEqual(app.session_state[self.prefix + ':layouts']['plate-2']['name'], 'Renamed second plate')
        self.assertEqual(app.multiselect(key=second + ':selected').value, ['G2'])
        app.selectbox(key=self.prefix + ':active').set_value('plate-1').run()
        self.assertEqual(app.radio(key=self.plate + ':layer').value, 'B overlay')
        self.assertEqual(app.radio(key=self.plate + ':selection_tool').value, 'Lasso')
        self.assertEqual(app.selectbox(key=self.plate + ':B:protein').value, 'protein:B1')
        self.assertEqual(app.multiselect(key=self.plate + ':selected').value, ['H3'])
        self.assertEqual(app.text_input(key=self.plate + ':label').value, 'First plate note')
        app.selectbox(key=self.prefix + ':active').set_value('plate-2').run()
        self.assertEqual(app.selectbox(key=second + ':A:protein').value, 'protein:A2')
        self.assertEqual(app.text_input(key=second + ':label').value, 'Second plate note')
        self.assertEqual(app.multiselect(key=second + ':selected').value, ['G2'])
        app.button(key=second + ':select_all').click().run()
        app.selectbox(key=self.prefix + ':active').set_value('plate-1').run()
        app.selectbox(key=self.prefix + ':active').set_value('plate-2').run()
        self.assertEqual(len(app.multiselect(key=second + ':selected').value), 96)
        app.button(key=second + ':deselect_all').click().run()
        app.selectbox(key=self.prefix + ':active').set_value('plate-1').run()
        app.selectbox(key=self.prefix + ':active').set_value('plate-2').run()
        self.assertEqual(app.multiselect(key=second + ':selected').value, [])
        self.assertTrue(all(plate['wells'] == {} for plate in app.session_state[self.prefix + ':layouts'].values()))
        self.assertFalse(app.exception)

    def test_missing_calibration_retains_assignments_and_can_clear_one_layer(self):
        self.assign('A', 'protein:A1', ['B1'])
        self.assign('B', 'protein:B1', ['B1'])
        app = self.app
        report = calculation_report()
        report['proteins'] = [protein for protein in report['proteins'] if protein['protein_id'] != 'A1']
        app.session_state['report_override'] = report
        app.run()
        self.assertEqual(app.session_state[self.prefix + ':layouts']['plate-1']['wells']['B1']['a_protein_id'], 'A1')
        self.assertTrue(any('missing from the current reader' in item.value for item in app.warning))
        self.assign('A', 'clear', ['B1'])
        item = app.session_state[self.prefix + ':layouts']['plate-1']['wells']['B1']
        self.assertEqual(item['a_protein_id'], '')
        self.assertEqual(item['b_protein_id'], 'B1')
        self.assertFalse(app.exception)

    def test_pending_b_choice_survives_layer_switch_and_protein_rename(self):
        app = self.app
        app.radio(key=self.plate + ':layer').set_value('B overlay').run()
        app.multiselect(key=self.plate + ':selected').set_value(['D3']).run()
        app.selectbox(key=self.plate + ':B:protein').set_value('protein:B2').run()
        self.assertEqual(app.session_state[self.prefix + ':layouts']['plate-1']['wells'], {})
        app.radio(key=self.plate + ':layer').set_value('A protein or mCherry').run()
        app.radio(key=self.plate + ':layer').set_value('B overlay').run()
        self.assertEqual(app.selectbox(key=self.plate + ':B:protein').value, 'protein:B2')
        report = calculation_report()
        next(protein for protein in report['proteins'] if protein['protein_id'] == 'B2')['protein_name'] = 'Renamed B two'
        app.session_state['report_override'] = report
        app.run()
        self.assertEqual(app.selectbox(key=self.plate + ':B:protein').value, 'protein:B2')
        self.assertIn('Renamed B two (B2)', app.selectbox(key=self.plate + ':B:protein').options)
        self.assertEqual(app.session_state[self.prefix + ':layouts']['plate-1']['wells'], {})
        app.button(key=self.plate + ':assign').click().run()
        self.assertEqual(app.session_state[self.prefix + ':layouts']['plate-1']['wells']['D3']['b_protein_id'], 'B2')
        self.assertFalse(app.exception)

    def test_pending_mcherry_volume_survives_hidden_controls(self):
        app = self.app
        app.multiselect(key=self.plate + ':selected').set_value(['C1']).run()
        app.selectbox(key=self.plate + ':A:protein').set_value('mcherry').run()
        app.checkbox(key=self.plate + ':set_control_volume').set_value(True).run()
        app.number_input(key=self.plate + ':control_volume').set_value(12.345).run()
        app.selectbox(key=self.plate + ':A:protein').set_value('protein:A2').run()
        app.selectbox(key=self.plate + ':A:protein').set_value('mcherry').run()
        self.assertTrue(app.checkbox(key=self.plate + ':set_control_volume').value)
        self.assertEqual(app.number_input(key=self.plate + ':control_volume').value, 12.345)
        app.radio(key=self.plate + ':layer').set_value('B overlay').run()
        app.radio(key=self.plate + ':layer').set_value('A protein or mCherry').run()
        self.assertEqual(app.selectbox(key=self.plate + ':A:protein').value, 'mcherry')
        self.assertTrue(app.checkbox(key=self.plate + ':set_control_volume').value)
        self.assertEqual(app.number_input(key=self.plate + ':control_volume').value, 12.345)
        app.checkbox(key=self.plate + ':set_control_volume').set_value(False).run()
        app.checkbox(key=self.plate + ':set_control_volume').set_value(True).run()
        self.assertEqual(app.number_input(key=self.plate + ':control_volume').value, 12.345)
        self.assertEqual(app.session_state[self.prefix + ':layouts']['plate-1']['wells'], {})
        app.button(key=self.plate + ':assign').click().run()
        item = app.session_state[self.prefix + ':layouts']['plate-1']['wells']['C1']
        self.assertEqual(item['a_control'], 'mCherry')
        self.assertEqual(item['control_volume_uL'], 12.345)
        self.assertFalse(app.exception)

    def test_note_only_action_is_explicit_and_preserves_b_assignments(self):
        app = self.app
        self.assign('B', 'protein:B1', ['E1'])
        app.multiselect(key=self.plate + ':selected').set_value(['E1', 'E2']).run()
        app.selectbox(key=self.plate + ':B:protein').set_value('keep').run()
        self.assertTrue(app.button(key=self.plate + ':assign').disabled)
        self.assertEqual(app.button(key=self.plate + ':assign').label, 'Save well note')
        self.assertEqual(app.text_input(key=self.plate + ':label').label, 'Well note (optional)')
        app.text_input(key=self.plate + ':label').set_value('Named well note').run()
        self.assertFalse(app.button(key=self.plate + ':assign').disabled)
        app.button(key=self.plate + ':assign').click().run()
        wells = app.session_state[self.prefix + ':layouts']['plate-1']['wells']
        self.assertEqual(wells['E1']['b_protein_id'], 'B1')
        self.assertEqual(wells['E2']['b_protein_id'], '')
        self.assertEqual(wells['E2']['label'], 'Named well note')
        self.assertFalse(app.exception)

    def test_empty_b_catalog_explains_how_to_create_calibrated_groups(self):
        app = self.app
        report = calculation_report()
        report['proteins'] = [protein for protein in report['proteins'] if protein['group'] != 'B']
        app.session_state['report_override'] = report
        app.radio(key=self.plate + ':layer').set_value('B overlay').run()
        self.assertTrue(any('On Reader plate B' in message.value and 'click Assign wells' in message.value
                            for message in app.info))
        self.assertEqual(app.selectbox(key=self.plate + ':B:protein').options,
                         ['Keep current assignment', 'Clear this layer'])
        self.assertFalse(app.exception)

    def test_restore_and_undo_preserve_pending_control_volume_and_plate_navigation(self):
        # AppTest has no upload driver; provide only the uploaded bytes while
        # exercising the real restore button, save callback, rerun and Undo.
        app = AppTest.from_string(
            'import io\n'
            'from unittest.mock import patch\n'
            'import streamlit as st\n'
            'from test_lucia_destination import calculation_report\n'
            'from lucia_destination_ui import render_destination_planner\n'
            'raw = st.session_state.get("saved_layout_upload")\n'
            'uploaded = io.BytesIO(raw) if raw is not None else None\n'
            'with patch("lucia_destination_ui.st.file_uploader", return_value=uploaded):\n'
            '    render_destination_planner(calculation_report(), "test")\n').run(timeout=20)
        app.selectbox(key=self.plate + ':A:protein').set_value('mcherry').run()
        app.checkbox(key=self.plate + ':set_control_volume').set_value(True).run()
        app.number_input(key=self.plate + ':control_volume').set_value(12.345).run()
        restored = create_plate({}, 'restored-plate', 'Restored plate')
        record = {'format': 'lucia-destination-layout', 'version': 1,
                  'source_sha256': 'workbook-hash', 'protein_names': {}, 'layouts': restored}
        app.session_state['saved_layout_upload'] = json.dumps(record).encode()
        app.run()
        app.button(key=self.prefix + ':restore').click().run()
        self.assertEqual(app.session_state[self.prefix + ':active'], 'restored-plate')
        self.assertEqual(app.session_state[self.prefix + ':layouts'], restored)
        self.assertEqual(app.session_state[self.plate + ':control_volume:pending_value'], 12.345)
        app.button(key=self.prefix + ':undo_button').click().run()
        self.assertEqual(app.session_state[self.prefix + ':active'], 'plate-1')
        self.assertEqual(app.selectbox(key=self.plate + ':A:protein').value, 'mcherry')
        self.assertTrue(app.checkbox(key=self.plate + ':set_control_volume').value)
        self.assertEqual(app.number_input(key=self.plate + ':control_volume').value, 12.345)
        # The still-uploaded JSON must not replace subsequent edits on reruns.
        app.multiselect(key=self.plate + ':selected').set_value(['F4']).run()
        app.button(key=self.plate + ':assign').click().run()
        self.assertEqual(list(app.session_state[self.prefix + ':layouts']), ['plate-1'])
        self.assertEqual(app.session_state[self.prefix + ':layouts']['plate-1']['wells']['F4']['control_volume_uL'], 12.345)
        self.assertFalse(app.exception)

    def test_manual_table_is_atomic_and_keeps_other_plate(self):
        catalog = protein_catalog(calculation_report())
        layouts = create_plate(create_plate({}, 'plate-1', 'First'), 'plate-2', 'Second')
        rows = destination_table_rows(layouts['plate-1'])
        rows[0].update({'A protein': 'A2', 'B protein': 'B1', 'Label': 'pair'})
        rows[1].update({'mCherry control': True, 'mCherry (µL)': 12.5, 'B protein': 'B2'})
        edited = apply_destination_table(layouts, 'plate-1', rows, catalog)
        self.assertEqual(edited['plate-2'], layouts['plate-2'])
        self.assertEqual(edited['plate-1']['wells']['A2']['a_control'], 'mCherry')
        self.assertEqual(edited['plate-1']['wells']['A1']['a_protein_id'], 'A2')
        self.assertEqual(layouts['plate-1']['wells'], {})
        rows[1]['A protein'] = 'A1'
        with self.assertRaisesRegex(ValueError, 'choose an A protein or mCherry'):
            apply_destination_table(layouts, 'plate-1', rows, catalog)
        self.assertEqual(layouts['plate-1']['wells'], {})
        figure = destination_figure(edited['plate-1'], catalog, ['A1'], 'B overlay', 'Click wells')
        self.assertIn('Name A2', figure.data[0].hovertext[0])
        self.assertIn('Name B1', figure.data[0].hovertext[0])
        self.assertEqual(figure.data[0].selectedpoints, (0,))

    def test_saved_draft_roundtrip_and_invalid_imports(self):
        catalog = protein_catalog(calculation_report())
        layouts = create_plate({}, 'plate-1', 'Saved')
        rows = destination_table_rows(layouts['plate-1'])
        rows[2].update({'mCherry control': True, 'B protein': 'B2', 'Label': 'unfinished'})
        layouts = apply_destination_table(layouts, 'plate-1', rows, catalog)
        record = {'format': 'lucia-destination-layout', 'version': 1,
                  'source_sha256': 'saved-source', 'protein_names': {'A': {}, 'B': {}}, 'layouts': layouts}
        restored, metadata = restore_destination_layout(json.dumps(record))
        self.assertEqual(restored, layouts)
        self.assertEqual(metadata['source_sha256'], 'saved-source')
        self.assertIsNone(restored['plate-1']['wells']['A3']['control_volume_uL'])
        for invalid in ('{"layouts": {}, "format":"lucia-destination-layout", "version": 1, "version": 1}',
                        json.dumps(dict(record, version=999)), json.dumps(dict(record, version=True)),
                        json.dumps(dict(record, extra=float('nan'))), '{', '[]'):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    restore_destination_layout(invalid)


if __name__ == '__main__':
    unittest.main()
