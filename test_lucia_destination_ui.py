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
        layer = 'A / mCherry' if group == 'A' else 'B overlay'
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
