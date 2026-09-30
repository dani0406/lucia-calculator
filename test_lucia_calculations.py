import unittest
from unittest.mock import patch
from types import SimpleNamespace
from lucia_calculations import A_DOSES, B_DOSES, calculate_workbook, fit_volume


class Sheet:
    def __getitem__(self, key):
        if key.startswith('F'):
            return SimpleNamespace(value=100)
        raise AssertionError('Raw input must only require measurement cells, not annotation cells.')


class Workbook:
    sheetnames = ['UL8 (A)', 'Binders (B)']

    def __getitem__(self, name):
        return Sheet()

    def close(self):
        pass


class CalculationTests(unittest.TestCase):
    def test_regression_orientation_and_intercept(self):
        fit = fit_volume([1, .5, .25, .125], [210, 110, 60, 35], 410)
        self.assertAlmostEqual(fit['slope'], 200)
        self.assertAlmostEqual(fit['intercept'], 10)
        self.assertAlmostEqual(fit['cfe_equivalent_uL'], 2)

    def test_invalid_calibrations(self):
        for y in [[None, 1, 2], [1, 1, 1], [1, 2, 3], [float('inf'), 2, 1]]:
            with self.assertRaises(ValueError):
                fit_volume([1, .1, .01], y, 100)

    def report_with_volumes(self, a_volume=30, b_volume=.5, strict=False, **kwargs):
        def fake_fit(doses, signals, target):
            return {'cfe_equivalent_uL': a_volume if doses == A_DOSES else b_volume,
                    'slope': 1, 'intercept': 0, 'r_squared': 1, 'extrapolated': True}
        with patch('lucia_calculations.load_workbook', return_value=Workbook()), patch('lucia_calculations.fit_volume', side_effect=fake_fit):
            return calculate_workbook(b'fixture', require_more_than_18=strict, **kwargs)

    def test_configurable_capacity_and_optional_names(self):
        self.assertFalse(self.report_with_volumes(minimum_samples=1)['errors'])
        self.assertTrue(self.report_with_volumes(minimum_samples=50)['errors'])
        self.assertFalse(self.report_with_volumes(a_volume=10.8, minimum_samples=50)['errors'])
        for invalid in [0, 51, 18.5, True]:
            with self.assertRaises(ValueError):
                self.report_with_volumes(minimum_samples=invalid)
        r = self.report_with_volumes(protein_names={'A1': ' My protein ', 'A2': ' '})
        self.assertEqual(r['proteins'][0]['protein_name'], 'My protein')
        self.assertEqual(r['proteins'][1]['protein_name'], 'A2')
        self.assertEqual(r['proteins'][2]['protein_name'], 'B1')

    def test_eighteen_passes_seventeen_fails(self):
        r = self.report_with_volumes()
        self.assertEqual(r['proteins'][0]['max_samples'], 18)
        self.assertFalse(r['errors'])
        self.assertTrue(self.report_with_volumes(a_volume=31)['errors'])
        self.assertTrue(self.report_with_volumes(strict=True)['errors'])

    def test_b_dilution_boundary_and_stage_pbs(self):
        r = self.report_with_volumes(b_volume=.5)
        b = r['proteins'][2]
        self.assertEqual(b['dilution_factor'], 10)
        self.assertEqual(b['dispense_uL'], 5)
        self.assertEqual(b['pbs_uL'], 195)
        self.assertEqual(r['proteins'][0]['pbs_uL'], 170)
        self.assertEqual(self.report_with_volumes(b_volume=1)['proteins'][2]['dilution_factor'], 1)
        self.assertTrue(self.report_with_volumes(b_volume=201)['errors'])


if __name__ == '__main__':
    unittest.main()
