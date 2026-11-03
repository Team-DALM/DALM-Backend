import pytest

from deploy.aws import migrate_postgres


@pytest.mark.parametrize(
    "code",
    [
        migrate_postgres.SOURCE_SETTINGS,
        migrate_postgres.SNAPSHOT,
        migrate_postgres.SOURCE_SQL,
        migrate_postgres.SNAPSHOT[: migrate_postgres.SNAPSHOT.index("async def main():")]
        + migrate_postgres.WRITE_CHECK,
    ],
)
def test_python_sent_to_database_client_is_valid(code):
    # These programs run in another container, so compiling the host script alone
    # cannot detect indentation errors introduced when orchestration is refactored.
    compile(code, "<database-client>", "exec")
