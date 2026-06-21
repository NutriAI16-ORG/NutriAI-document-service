import uuid
from unittest.mock import MagicMock
from app.models import GUID

def test_guid_type():
    # Mock dialects
    pg_dialect = MagicMock()
    pg_dialect.name = 'postgresql'
    
    sqlite_dialect = MagicMock()
    sqlite_dialect.name = 'sqlite'
    
    guid = GUID()
    
    # Test load_dialect_impl
    guid.load_dialect_impl(pg_dialect)
    guid.load_dialect_impl(sqlite_dialect)
    
    # Test process_bind_param
    val = uuid.uuid4()
    val_str = str(val)
    
    # SQLite paths
    assert guid.process_bind_param(None, sqlite_dialect) is None
    assert guid.process_bind_param(val, sqlite_dialect) == val_str
    assert guid.process_bind_param(val_str, sqlite_dialect) == val_str
    
    # PostgreSQL paths
    assert guid.process_bind_param(None, pg_dialect) is None
    assert guid.process_bind_param(val, pg_dialect) == val
    assert guid.process_bind_param(val_str, pg_dialect) == val
    
    # Test process_result_value
    assert guid.process_result_value(None, sqlite_dialect) is None
    assert guid.process_result_value(val, sqlite_dialect) == val
    assert guid.process_result_value(val_str, sqlite_dialect) == val
