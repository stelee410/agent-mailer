import pytest
from agent_mailer.routes.admin import HUMAN_OPERATOR_ADDRESS, HUMAN_OPERATOR_ID


@pytest.fixture
async def agents(client):
    """Register planner, coder, reviewer and return {name: {id, address}}."""
    result = {}
    for name in ("planner", "coder", "reviewer"):
        resp = await client.post("/agents/register", json={
            "name": name, "role": name, "description": f"{name} agent",
            "system_prompt": f"你是一个{name}。",
        })
        data = resp.json()
        result[name] = {"id": data["id"], "address": data["address"]}
    return result


# --- Stats ---

async def test_stats_empty(client):
    resp = await client.get("/admin/agents/stats")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_threads_summary_empty(client):
    resp = await client.get("/admin/threads/summary")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_threads_summary(client, agents):
    await client.post("/messages/send", json={
        "agent_id": agents["planner"]["id"],
        "from_agent": agents["planner"]["address"],
        "to_agent": agents["coder"]["address"],
        "action": "send",
        "subject": "Alpha",
        "body": "First",
    })
    send2 = await client.post("/messages/send", json={
        "agent_id": agents["planner"]["id"],
        "from_agent": agents["planner"]["address"],
        "to_agent": agents["reviewer"]["address"],
        "action": "send",
        "subject": "Beta",
        "body": "Other thread",
    })
    thread_b = send2.json()["thread_id"]
    first_beta_msg = send2.json()["id"]
    await client.post("/messages/send", json={
        "agent_id": agents["reviewer"]["id"],
        "from_agent": agents["reviewer"]["address"],
        "to_agent": agents["planner"]["address"],
        "action": "reply",
        "subject": "Re: Beta — follow up",
        "body": "Done",
        "parent_id": first_beta_msg,
    })

    resp = await client.get("/admin/threads/summary")
    assert resp.status_code == 200
    summaries = resp.json()
    assert len(summaries) == 2
    # Newest thread first (reply bumped Beta thread)
    assert summaries[0]["thread_id"] == thread_b
    # preview_subject = first message in thread, not latest reply
    assert summaries[0]["preview_subject"] == "Beta"
    assert summaries[0]["message_count"] == 2
    assert summaries[0]["unread_count"] == 2


async def test_thread_archive_and_summary_filter(client, agents):
    send = await client.post("/messages/send", json={
        "agent_id": agents["planner"]["id"],
        "from_agent": agents["planner"]["address"],
        "to_agent": agents["coder"]["address"],
        "action": "send",
        "subject": "Keep me",
        "body": "x",
    })
    tid = send.json()["thread_id"]

    st = await client.get(f"/admin/threads/{tid}/archive")
    assert st.status_code == 200
    assert st.json() == {"archived": False, "archived_at": None}

    bad = await client.post("/admin/threads/not-a-real-thread-id/archive")
    assert bad.status_code == 404

    arc = await client.post(f"/admin/threads/{tid}/archive")
    assert arc.status_code == 200
    assert arc.json()["thread_id"] == tid

    st2 = await client.get(f"/admin/threads/{tid}/archive")
    assert st2.json()["archived"] is True
    assert st2.json()["archived_at"]

    active = await client.get("/admin/threads/summary")
    assert len(active.json()) == 0

    archived = await client.get("/admin/threads/summary", params={"archived": True})
    ar_list = archived.json()
    assert len(ar_list) == 1
    assert ar_list[0]["thread_id"] == tid
    assert ar_list[0]["preview_subject"] == "Keep me"
    assert ar_list[0]["archived_at"]

    un = await client.post(f"/admin/threads/{tid}/unarchive")
    assert un.status_code == 200

    active2 = await client.get("/admin/threads/summary")
    assert len(active2.json()) == 1


async def test_stats_counts(client, agents):
    # planner sends 2 messages to coder
    for i in range(2):
        await client.post("/messages/send", json={
            "agent_id": agents["planner"]["id"],
            "from_agent": agents["planner"]["address"],
            "to_agent": agents["coder"]["address"],
            "action": "send",
            "subject": f"Task {i}",
            "body": f"Do {i}",
        })

    # coder reads one
    inbox = await client.get(
        f"/messages/inbox/{agents['coder']['address']}",
        params={"agent_id": agents["coder"]["id"]},
    )
    first_msg = inbox.json()[0]
    await client.patch(f"/messages/{first_msg['id']}/read")

    # coder replies to that one
    await client.post("/messages/send", json={
        "agent_id": agents["coder"]["id"],
        "from_agent": agents["coder"]["address"],
        "to_agent": agents["planner"]["address"],
        "action": "reply",
        "body": "Done",
        "parent_id": first_msg["id"],
    })

    resp = await client.get("/admin/agents/stats")
    assert resp.status_code == 200
    stats = {s["address"]: s for s in resp.json()}

    planner = stats["planner@local"]
    assert planner["messages_sent"] == 2
    assert planner["messages_received"] == 1  # the reply
    assert planner["messages_unread"] == 1

    coder = stats["coder@local"]
    assert coder["messages_received"] == 2
    assert coder["messages_read"] == 1
    assert coder["messages_unread"] == 1
    assert coder["messages_sent"] == 1
    assert coder["messages_replied"] == 1


# --- Admin Inbox ---

async def test_admin_inbox_no_auth(client, agents):
    """Admin inbox does not require agent_id verification."""
    await client.post("/messages/send", json={
        "agent_id": agents["planner"]["id"],
        "from_agent": agents["planner"]["address"],
        "to_agent": agents["coder"]["address"],
        "action": "send",
        "subject": "Task",
        "body": "Do this",
    })
    resp = await client.get(f"/admin/messages/inbox/{agents['coder']['address']}")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_admin_inbox_all(client, agents):
    send_resp = await client.post("/messages/send", json={
        "agent_id": agents["planner"]["id"],
        "from_agent": agents["planner"]["address"],
        "to_agent": agents["coder"]["address"],
        "action": "send",
        "subject": "Task",
        "body": "Do",
    })
    msg_id = send_resp.json()["id"]
    await client.patch(f"/messages/{msg_id}/read")

    # unread only
    resp = await client.get(f"/admin/messages/inbox/{agents['coder']['address']}")
    assert len(resp.json()) == 0

    # all
    resp = await client.get(f"/admin/messages/inbox/{agents['coder']['address']}?all=true")
    assert len(resp.json()) == 1


async def test_admin_inbox_does_not_mark_read(client, agents):
    """Peeking via admin inbox should not change is_read status."""
    await client.post("/messages/send", json={
        "agent_id": agents["planner"]["id"],
        "from_agent": agents["planner"]["address"],
        "to_agent": agents["coder"]["address"],
        "action": "send",
        "subject": "Task",
        "body": "Do",
    })

    # peek twice
    await client.get(f"/admin/messages/inbox/{agents['coder']['address']}")
    await client.get(f"/admin/messages/inbox/{agents['coder']['address']}")

    # still unread via normal inbox
    resp = await client.get(
        f"/messages/inbox/{agents['coder']['address']}",
        params={"agent_id": agents["coder"]["id"]},
    )
    assert len(resp.json()) == 1
    assert resp.json()[0]["is_read"] is False


# --- Admin Send ---

async def test_admin_send(client, agents):
    resp = await client.post("/admin/messages/send", json={
        "to_agent": agents["coder"]["address"],
        "subject": "Hello from human",
        "body": "Please do this task",
    })
    assert resp.status_code == 200
    msg = resp.json()
    assert msg["from_agent"] == HUMAN_OPERATOR_ADDRESS
    assert msg["to_agent"] == agents["coder"]["address"]
    assert msg["action"] == "send"


async def test_admin_send_creates_human_operator(client, agents):
    await client.post("/admin/messages/send", json={
        "to_agent": agents["coder"]["address"],
        "subject": "Test",
        "body": "Body",
    })
    # human operator agent should exist
    resp = await client.get(f"/agents/{HUMAN_OPERATOR_ID}")
    assert resp.status_code == 200
    assert resp.json()["address"] == HUMAN_OPERATOR_ADDRESS


async def test_admin_send_idempotent_human_operator(client, agents):
    """Sending multiple times should not fail due to duplicate human operator."""
    for i in range(3):
        resp = await client.post("/admin/messages/send", json={
            "to_agent": agents["coder"]["address"],
            "subject": f"Test {i}",
            "body": f"Body {i}",
        })
        assert resp.status_code == 200


async def test_admin_send_invalid_recipient(client, agents):
    resp = await client.post("/admin/messages/send", json={
        "to_agent": "nonexistent@local",
        "subject": "Test",
        "body": "Body",
    })
    assert resp.status_code == 404


async def test_admin_send_reply(client, agents):
    # first send
    send_resp = await client.post("/admin/messages/send", json={
        "to_agent": agents["coder"]["address"],
        "subject": "Task",
        "body": "Do this",
    })
    msg_id = send_resp.json()["id"]
    thread_id = send_resp.json()["thread_id"]

    # reply
    reply_resp = await client.post("/admin/messages/send", json={
        "to_agent": agents["coder"]["address"],
        "action": "reply",
        "subject": "Re: Task",
        "body": "Follow up",
        "parent_id": msg_id,
    })
    assert reply_resp.status_code == 200
    assert reply_resp.json()["thread_id"] == thread_id
    assert reply_resp.json()["action"] == "reply"


async def test_admin_send_reply_requires_parent(client, agents):
    resp = await client.post("/admin/messages/send", json={
        "to_agent": agents["coder"]["address"],
        "action": "reply",
        "body": "No parent",
    })
    assert resp.status_code == 400


# --- UI ---

async def test_ui_returns_html(client):
    resp = await client.get("/admin/ui")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Agent Mailer" in resp.text
    assert "Operator Console" in resp.text
    assert "Archive" in resp.text
