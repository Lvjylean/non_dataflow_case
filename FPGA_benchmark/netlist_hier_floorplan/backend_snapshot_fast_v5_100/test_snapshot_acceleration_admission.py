"""Old or incomplete native evidence cannot enable the new production copy."""
import copy
from pathlib import Path
import tempfile
import unittest

from run_case import source_hashes, validate_snapshot_acceleration_admission


class Admission(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name)
        (self.source/'physical_eco.tcl').write_text('# physical\n')
        (self.source/'candidate.tcl').write_text('# candidate\n')
        hashes = source_hashes(self.source)
        self.validation = dict(source_hashes=hashes,
            native_snapshot_acceleration_evidence=dict(status='PASS',
                schema='native-snapshot-acceleration-v2', source_hashes=copy.copy(hashes),
                cleanup_affected_and_route_state_equivalent=True,
                complete_verification_reports_equivalent=True,
                candidate_readback_and_plan_equivalent=True))

    def test_complete_current_evidence(self):
        validate_snapshot_acceleration_admission(self.validation,self.source,True)

    def test_missing_false_or_wrong_schema_rejected(self):
        for key in ('status','schema','cleanup_affected_and_route_state_equivalent',
                    'complete_verification_reports_equivalent','candidate_readback_and_plan_equivalent'):
            proof=copy.deepcopy(self.validation)
            proof['native_snapshot_acceleration_evidence'].pop(key)
            with self.assertRaises(ValueError):
                validate_snapshot_acceleration_admission(proof,self.source,True)
        with self.assertRaises(ValueError):
            validate_snapshot_acceleration_admission({},self.source,True)

    def test_nonlocality_still_requires_cleanup_and_verification(self):
        self.validation['native_snapshot_acceleration_evidence'].pop('candidate_readback_and_plan_equivalent')
        validate_snapshot_acceleration_admission(self.validation,self.source,False)
        self.validation['native_snapshot_acceleration_evidence']['cleanup_affected_and_route_state_equivalent']=False
        with self.assertRaises(ValueError):
            validate_snapshot_acceleration_admission(self.validation,self.source,False)

    def test_stale_or_partial_source_rejected(self):
        proof=copy.deepcopy(self.validation)
        proof['native_snapshot_acceleration_evidence']['source_hashes']['candidate.tcl']='old'
        with self.assertRaises(ValueError):
            validate_snapshot_acceleration_admission(proof,self.source,True)
        (self.source/'new.tcl').write_text('# unvalidated\n')
        with self.assertRaises(ValueError):
            validate_snapshot_acceleration_admission(self.validation,self.source,True)


if __name__=='__main__':
    unittest.main()
