"""
Tests that dependencies.py does not contain inline DDL (CREATE TABLE).

Written to verify HIGH-05: DDL should be in migrations, not hot paths.
"""

import inspect

import pytest


class TestNoInlineDDL:
    """Verify dependencies.py doesn't run CREATE TABLE at runtime."""

    def test_store_dependencies_no_create_table(self):
        from elephantq.features.dependencies import store_job_dependencies

        source = inspect.getsource(store_job_dependencies)
        assert "CREATE TABLE" not in source, (
            "store_job_dependencies() still contains inline CREATE TABLE DDL"
        )

    def test_store_dependencies_with_conn_no_create_table(self):
        from elephantq.features.dependencies import _store_dependencies_with_conn

        source = inspect.getsource(_store_dependencies_with_conn)
        assert "CREATE TABLE" not in source, (
            "_store_dependencies_with_conn() still contains inline CREATE TABLE DDL"
        )
