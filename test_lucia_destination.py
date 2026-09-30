import copy
import unittest

from lucia_calculations import calculate_records
from lucia_destination import (assign_destination_wells, build_transfer_preview,
                               clear_destination_wells, create_plate, protein_catalog,
                               remove_plate, rename_plate, validate_layouts)


def calculation_report():
    records = []
    for group, identity, volume, target in [('A', 'A1', 20, 100_000_000),
                                             ('A', 'A2', 10, 100_000_000),
                                             ('B', 'B1', .35, 400_000_000),
                                             ('B', 'B2', 2, 400_000_000)]:
        slope = target / volume
        records.append({'group': group, 'protein_id': identity, 'protein_name': f'Name {identity}',
                        'sheet': f'Reader {group}', 'reader_wells': ['F1', 'F2'],
                        'signal_cells': ['F40', 'F41'], 'calibration_cfe_uL': [1, 2],
                        'signals': [slope, slope * 2], 'target_signal': target,
                        'target_pmol': 20 if group == 'A' else 40})
    return calculate_records(records, 18, 'workbook-hash', {'A': 'F', 'B': 'G'})


class DestinationTests(unittest.TestCase):
    def setUp(self):
        self.report = calculation_report()
        self.catalog = protein_catalog(self.report)
        self.layouts = create_plate({}, 'plate-1', 'LUCIA A1')

    def assign(self, layouts=None, wells=('A1',), **updates):
        return assign_destination_wells(self.layouts if layouts is None else layouts,
                                        'plate-1', wells, catalog=self.catalog, **updates)

    def test_edits_are_atomic_and_preserve_independent_stage_assignments(self):
        start = copy.deepcopy(self.layouts)
        assigned = self.assign(wells=['A10', 'A2'], a_protein_id='A1', label='pair')
        edited = self.assign(assigned, ['A2'], b_protein_id='B1')
        self.assertEqual(self.layouts, start)
        self.assertEqual(list(assigned['plate-1']['wells']), ['A2', 'A10'])
        self.assertEqual(edited['plate-1']['wells']['A2'],
                         {'a_protein_id': 'A1', 'b_protein_id': 'B1', 'label': 'pair',
                          'a_control': '', 'control_volume_uL': None})
        self.assertEqual(assigned['plate-1']['wells']['A2']['b_protein_id'], '')
        before = copy.deepcopy(edited)
        with self.assertRaisesRegex(ValueError, 'A1–H12|A1 and H12'):
            self.assign(edited, ['A1', 'A13'], a_protein_id='A2')
        with self.assertRaisesRegex(ValueError, 'Unknown protein B'):
            self.assign(edited, ['A2'], b_protein_id='missing')
        self.assertEqual(edited, before)
        cleared = self.assign(edited, ['A2'], a_protein_id='')
        self.assertEqual(cleared['plate-1']['wells']['A2']['b_protein_id'], 'B1')
        removed = clear_destination_wells(edited, 'plate-1', ['A10'])
        self.assertEqual(list(removed['plate-1']['wells']), ['A2'])
        renamed = rename_plate(removed, 'plate-1', 'Renamed')
        self.assertEqual(renamed['plate-1']['name'], 'Renamed')
        self.assertEqual(remove_plate(renamed, 'plate-1'), {})
        with self.assertRaisesRegex(ValueError, 'already exists'):
            create_plate(edited, 'plate-1', 'Duplicate')

    def test_transfer_preview_preserves_precision_provenance_and_stages(self):
        layouts = self.assign(wells=['A10', 'A2'], a_protein_id='A1', b_protein_id='B1')
        original = copy.deepcopy((self.report, layouts))
        preview = build_transfer_preview(self.report, layouts)
        self.assertTrue(preview['ready'], preview['errors'])
        rows = preview['transfers']
        self.assertEqual([(row['well'], row['stage']) for row in rows],
                         [('A2', 'A'), ('A2', 'B'), ('A10', 'A'), ('A10', 'B')])
        for row in rows:
            self.assertAlmostEqual(row['dispense_uL'] + row['pbs_uL'], 200)
            expected = self.catalog[row['stage']][row['protein_id']]
            self.assertEqual(row['dispense_uL'], expected['dispense_uL'])
            self.assertEqual(row['cfe_equivalent_uL'], expected['cfe_equivalent_uL'])
            self.assertEqual(row['provenance']['source_sha256'], 'workbook-hash')
            self.assertEqual(row['provenance']['signal_cells'], ['F40', 'F41'])
        self.assertEqual(rows[1]['provenance']['signal_column'], 'G')
        self.assertTrue(rows[1]['requires_prepared_solution'])
        self.assertEqual(rows[1]['dilution_factor'], 10)
        self.assertFalse(rows[0]['requires_prepared_solution'])
        self.assertEqual(len(preview['warnings']), 1)
        self.assertEqual((self.report, layouts), original)
        rows[0]['provenance']['signal_cells'][0] = 'changed'
        preview['layouts']['plate-1']['wells']['A2']['label'] = 'changed'
        self.assertEqual((self.report, layouts), original)

    def test_capacity_counts_across_plates_and_recomputes_stale_max_samples(self):
        layouts = self.assign(wells=[f'A{i}' for i in range(1, 13)] + ['B1'],
                              a_protein_id='A1', b_protein_id='B2')
        layouts = create_plate(layouts, 'plate-2', 'LUCIA replicate')
        layouts = assign_destination_wells(layouts, 'plate-2',
                                          [f'A{i}' for i in range(1, 13)] + ['B1', 'B2'],
                                          a_protein_id='A1', b_protein_id='B2', catalog=self.catalog)
        self.report['proteins'][0]['max_samples'] = 999
        preview = build_transfer_preview(self.report, layouts)
        self.assertTrue(preview['ready'], preview['errors'])
        self.assertEqual(preview['a_usage'][0]['assigned_wells'], 27)
        self.assertEqual(preview['a_usage'][0]['max_samples'], 27)
        self.assertEqual(preview['a_usage'][0]['remaining_cfe_uL'], 0)
        layouts = self.assign(layouts, ['B2'], a_protein_id='A1', b_protein_id='B2')
        preview = build_transfer_preview(self.report, layouts)
        self.assertFalse(preview['ready'])
        self.assertIn('28 assigned wells exceed the 27-well capacity', ' '.join(preview['errors']))

    def test_drafts_invalid_calculations_and_missing_catalog_entries_block_ready(self):
        partial = self.assign(a_protein_id='A1')
        preview = build_transfer_preview(self.report, partial)
        self.assertFalse(preview['ready'])
        self.assertIn('assign protein B', ' '.join(preview['errors']))
        self.assertEqual(len(preview['transfers']), 1)
        self.assertEqual(partial['plate-1']['wells']['A1']['b_protein_id'], '')
        paired = self.assign(partial, b_protein_id='B1')
        self.report['proteins'][2]['errors'] = ['Calibration rejected.']
        preview = build_transfer_preview(self.report, paired)
        self.assertIn('Calibration rejected.', ' '.join(preview['errors']))
        self.assertFalse(preview['ready'])
        self.assertEqual([row['stage'] for row in preview['transfers']], ['A'])
        unrelated = self.assign(b_protein_id='B2', a_protein_id='A2')
        self.assertTrue(build_transfer_preview(self.report, unrelated)['ready'])
        stale = copy.deepcopy(paired)
        stale['plate-1']['wells']['A1']['a_protein_id'] = 'gone'
        self.assertIn('unknown protein A ID gone', ' '.join(build_transfer_preview(self.report, stale)['errors']))
        stale['plate-1']['wells']['Z1'] = stale['plate-1']['wells'].pop('A1')
        self.assertIn('invalid destination well Z1', ' '.join(build_transfer_preview(self.report, stale)['errors']))

    def test_duplicate_ids_and_inconsistent_volume_records_are_rejected(self):
        duplicate = copy.deepcopy(self.report)
        duplicate['proteins'].append(copy.deepcopy(duplicate['proteins'][0]))
        with self.assertRaisesRegex(ValueError, 'Duplicate protein ID'):
            protein_catalog(duplicate)
        layouts = self.assign(a_protein_id='A1', b_protein_id='B1')
        self.report['proteins'][2]['pbs_uL'] = 150
        result = build_transfer_preview(self.report, layouts)
        self.assertFalse(result['ready'])
        self.assertIn('must total 200', ' '.join(result['errors']))
        self.assertFalse(build_transfer_preview(calculation_report(), self.layouts)['ready'])

    def test_mcherry_is_an_independent_first_stage_control(self):
        layouts = self.assign(a_protein_id='A1', b_protein_id='B1')
        control = self.assign(layouts, a_control='mCherry')
        self.assertEqual(control['plate-1']['wells']['A1']['a_protein_id'], '')
        preview = build_transfer_preview(self.report, control)
        self.assertFalse(preview['ready'])
        self.assertIn('mCherry volume not configured', ' '.join(preview['errors']))
        self.assertNotIn('assign protein A', ' '.join(preview['errors']))
        ready = self.assign(control, control_volume_uL=12.3456789)
        edited_b = self.assign(ready, b_protein_id='B2')
        preview = build_transfer_preview(self.report, edited_b)
        self.assertTrue(preview['ready'], preview['errors'])
        row = preview['transfers'][0]
        self.assertEqual((row['stage'], row['kind'], row['protein_id']), ('A', 'control', 'mCherry'))
        self.assertEqual(row['dispense_uL'], 12.3456789)
        self.assertEqual(row['pbs_uL'], 200 - 12.3456789)
        self.assertEqual(preview['a_usage'], [])
        self.assertEqual(edited_b['plate-1']['wells']['A1']['control_volume_uL'], 12.3456789)
        replaced = self.assign(edited_b, a_protein_id='A2')
        self.assertEqual(replaced['plate-1']['wells']['A1']['a_control'], '')
        self.assertIsNone(replaced['plate-1']['wells']['A1']['control_volume_uL'])
        with self.assertRaisesRegex(ValueError, 'both an A protein and mCherry'):
            self.assign(a_protein_id='A1', a_control='mCherry')
        with self.assertRaisesRegex(ValueError, 'mCherry volume'):
            self.assign(a_control='mCherry', control_volume_uL=0)
        bad = copy.deepcopy(ready)
        bad['plate-1']['wells']['A1']['a_protein_id'] = 'A1'
        with self.assertRaisesRegex(ValueError, 'both an A protein and mCherry'):
            validate_layouts(bad)
        cleared = self.assign(edited_b, a_control='', control_volume_uL='')
        self.assertIsNone(cleared['plate-1']['wells']['A1']['control_volume_uL'])

    def test_restored_layouts_reject_nonfinite_or_non_json_metadata(self):
        layouts = self.assign(a_control='mCherry', control_volume_uL=15,
                              b_protein_id='B1', label='control')
        layouts['plate-1']['metadata'] = {'description': 'saved layout', 'revision': [1, 2]}
        original = copy.deepcopy(layouts)
        restored = validate_layouts(layouts)
        self.assertEqual(restored, original)
        restored['plate-1']['metadata']['revision'].append(3)
        restored['plate-1']['wells']['A1']['control_volume_uL'] = 20
        self.assertEqual(layouts, original)
        for value in (float('nan'), float('inf'), float('-inf'), object(), {1, 2}):
            with self.subTest(value=value):
                invalid = copy.deepcopy(layouts)
                invalid['plate-1']['metadata']['extra'] = value
                with self.assertRaisesRegex(ValueError, 'JSON-compatible values and finite numbers'):
                    validate_layouts(invalid)
                preview = build_transfer_preview(self.report, invalid)
                self.assertFalse(preview['ready'])
                self.assertIn('JSON-compatible values and finite numbers', ' '.join(preview['errors']))
        self.assertEqual(layouts, original)


if __name__ == '__main__':
    unittest.main()
