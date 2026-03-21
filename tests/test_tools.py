from __future__ import annotations

import pytest

from modules.clients.service import ClientService
from modules.factures.service import InvoiceService
from tools.client_tool import ClientTool
from tools.invoice_tool import InvoiceTool
from tools.postgres_tool import PostgresTool


@pytest.mark.asyncio
async def test_client_tool_create_list(fake_store):
    service = ClientService(store=fake_store)
    tool = ClientTool(service)

    created = await tool.run(action="create", payload={"data": {"name": "ACME"}})
    assert created["status"] == "created"

    listed = await tool.run(action="list")
    assert listed["clients"][0]["name"] == "ACME"


@pytest.mark.asyncio
async def test_invoice_tool_create_list(fake_store):
    service = InvoiceService(store=fake_store)
    tool = InvoiceTool(service)

    created = await tool.run(action="create", payload={"data": {"montant_ht": 1200}})
    assert created["status"] == "created"

    listed = await tool.run(action="list")
    assert listed["factures"][0]["montant_ht"] == 1200


@pytest.mark.asyncio
async def test_postgres_tool_query_select_only(fake_store):
    tool = PostgresTool(store=fake_store)
    with pytest.raises(ValueError):
        await tool.run(action="query", payload={"sql": "update clients set name='x'"})
