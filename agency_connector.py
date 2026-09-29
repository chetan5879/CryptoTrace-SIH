"""Extension boundary for a future authorised agency integration.
Implement only after obtaining an official interface contract. No generic URL
or bearer token sender is exposed: that would risk disclosing victim records.
"""
from typing import Protocol
class AgencyConnector(Protocol):
    def validate_configuration(self) -> None: ...
    def submit_case(self, payload: dict, idempotency_key: str) -> dict: ...
    def submission_status(self, reference: str) -> dict: ...

class UnconfiguredAgencyConnector:
    def validate_configuration(self):
        raise RuntimeError('Official agency API specification, credentials and acceptance testing required')
    def submit_case(self,payload,idempotency_key):self.validate_configuration()
    def submission_status(self,reference):self.validate_configuration()
