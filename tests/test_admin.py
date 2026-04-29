import pytest
from agent_mailer.routes.admin import _human_operator_address


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


async def test_threads_summary_archived_and_trashed_mutual_exclusive(client):
    resp = await client.get("/admin/threads/summary", params={"archived": True, "trashed": True})
    assert resp.status_code == 400


async def test_thread_trash_restore_purge(client, agents):
    send = await client.post("/messages/send", json={
        "agent_id": agents["planner"]["id"],
        "from_agent": agents["planner"]["address"],
        "to_agent": agents["coder"]["address"],
        "action": "send",
        "subject": "Trash me",
        "body": "body",
    })
    tid = send.json()["thread_id"]
    mid = send.json()["id"]

    st0 = await client.get(f"/admin/threads/{tid}/status")
    assert st0.json()["trashed"] is False

    tr = await client.post(f"/admin/threads/{tid}/trash")
    assert tr.status_code == 200

    active = await client.get("/admin/threads/summary")
    assert len(active.json()) == 0
    trashed = await client.get("/admin/threads/summary", params={"trashed": True})
    assert len(trashed.json()) == 1

    st1 = await client.get(f"/admin/threads/{tid}/status")
    assert st1.json()["trashed"] is True

    # Thread still visible via agent endpoint (messages exist, just in trash)
    # But trashed thread messages are filtered, so thread check may return 404

    rs = await client.post(f"/admin/threads/{tid}/restore")
    assert rs.status_code == 200
    assert len((await client.get("/admin/threads/summary")).json()) == 1

    await client.post(f"/admin/threads/{tid}/trash")
    pu = await client.post(f"/admin/threads/{tid}/purge")
    assert pu.status_code == 200
    assert len((await client.get("/admin/threads/summary", params={"trashed": True})).json()) == 0

    # After purge, message is gone
    nf = await client.patch(f"/messages/{mid}/read")
    assert nf.status_code == 404


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

    planner_stats = stats[agents["planner"]["address"]]
    assert planner_stats["messages_sent"] == 2
    assert planner_stats["messages_received"] == 1  # the reply
    assert planner_stats["messages_unread"] == 1

    coder_stats = stats[agents["coder"]["address"]]
    assert coder_stats["messages_received"] == 2
    assert coder_stats["messages_read"] == 1
    assert coder_stats["messages_unread"] == 1
    assert coder_stats["messages_sent"] == 1
    assert coder_stats["messages_replied"] == 1


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


async def test_admin_inbox_filters_human_operator_by_sender_team(client, agents):
    human = (await client.get("/admin/human-operator")).json()
    alpha = (await client.post("/admin/teams", json={"name": "Alpha"})).json()["id"]
    beta = (await client.post("/admin/teams", json={"name": "Beta"})).json()["id"]
    await client.post(f"/admin/teams/{alpha}/agents", json={"agent_id": agents["planner"]["id"]})
    await client.post(f"/admin/teams/{beta}/agents", json={"agent_id": agents["coder"]["id"]})

    for subject in ("Alpha 1", "Alpha 2"):
        await client.post("/messages/send", json={
            "agent_id": agents["planner"]["id"],
            "from_agent": agents["planner"]["address"],
            "to_agent": human["address"],
            "action": "send",
            "subject": subject,
            "body": "from alpha",
        })
    await client.post("/messages/send", json={
        "agent_id": agents["coder"]["id"],
        "from_agent": agents["coder"]["address"],
        "to_agent": human["address"],
        "action": "send",
        "subject": "Beta 1",
        "body": "from beta",
    })

    inbox_url = f"/admin/messages/inbox/{human['address']}"
    all_resp = await client.get(inbox_url, params={"all": "true"})
    assert all_resp.status_code == 200
    assert {m["subject"] for m in all_resp.json()} == {"Alpha 1", "Alpha 2", "Beta 1"}

    alpha_resp = await client.get(inbox_url, params={"all": "true", "from_team_id": alpha})
    assert alpha_resp.status_code == 200
    assert {m["subject"] for m in alpha_resp.json()} == {"Alpha 1", "Alpha 2"}

    beta_resp = await client.get(inbox_url, params={"all": "true", "from_team_id": beta})
    assert beta_resp.status_code == 200
    assert {m["subject"] for m in beta_resp.json()} == {"Beta 1"}

    paged_resp = await client.get(
        inbox_url, params={"all": "true", "from_team_id": alpha, "page": 1, "page_size": 1}
    )
    assert paged_resp.status_code == 200
    assert paged_resp.json()["total"] == 2
    assert paged_resp.json()["total_pages"] == 2
    assert len(paged_resp.json()["messages"]) == 1

    missing_resp = await client.get(inbox_url, params={"all": "true", "from_team_id": "missing-team"})
    assert missing_resp.status_code == 404


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


async def test_inbox_hides_archived_and_trashed_thread_messages(client, agents):
    send = await client.post("/messages/send", json={
        "agent_id": agents["planner"]["id"],
        "from_agent": agents["planner"]["address"],
        "to_agent": agents["coder"]["address"],
        "action": "send",
        "subject": "Hidden when filed",
        "body": "x",
    })
    tid = send.json()["thread_id"]

    async def coder_inbox_all():
        return await client.get(
            f"/messages/inbox/{agents['coder']['address']}",
            params={"agent_id": agents["coder"]["id"], "all": "true"},
        )

    async def admin_inbox_all():
        return await client.get(
            f"/admin/messages/inbox/{agents['coder']['address']}?all=true",
        )

    assert len((await coder_inbox_all()).json()) == 1
    assert len((await admin_inbox_all()).json()) == 1

    await client.post(f"/admin/threads/{tid}/archive")
    assert (await coder_inbox_all()).json() == []
    assert (await admin_inbox_all()).json() == []

    await client.post(f"/admin/threads/{tid}/unarchive")
    assert len((await coder_inbox_all()).json()) == 1

    await client.post(f"/admin/threads/{tid}/trash")
    assert (await coder_inbox_all()).json() == []
    assert (await admin_inbox_all()).json() == []

    await client.post(f"/admin/threads/{tid}/restore")
    assert len((await coder_inbox_all()).json()) == 1


async def test_trash_single_message_leaf_only(client, agents):
    send = await client.post("/messages/send", json={
        "agent_id": agents["planner"]["id"],
        "from_agent": agents["planner"]["address"],
        "to_agent": agents["coder"]["address"],
        "action": "send",
        "subject": "Leaf only",
        "body": "x",
    })
    mid = send.json()["id"]
    tid = send.json()["thread_id"]

    r = await client.post(f"/admin/messages/{mid}/trash")
    assert r.status_code == 200

    inbox = await client.get(
        f"/messages/inbox/{agents['coder']['address']}",
        params={"agent_id": agents["coder"]["id"], "all": "true"},
    )
    assert inbox.json() == []

    listed = await client.get("/admin/trash/messages")
    assert len(listed.json()) == 1
    assert listed.json()[0]["message_id"] == mid

    detail = await client.get(f"/admin/trash/messages/{mid}")
    assert detail.status_code == 200
    assert detail.json()["message"]["id"] == mid

    # After trashing the only message, thread has no visible messages
    # Agent thread endpoint returns 404 (no messages involving user)
    thread_msgs = await client.get(f"/messages/thread/{tid}")
    assert thread_msgs.status_code == 404

    await client.post(f"/admin/messages/{mid}/restore")
    assert len((await client.get(
        f"/messages/inbox/{agents['coder']['address']}",
        params={"agent_id": agents["coder"]["id"], "all": "true"},
    )).json()) == 1


async def test_trash_single_message_rejected_when_has_reply(client, agents):
    send = await client.post("/messages/send", json={
        "agent_id": agents["planner"]["id"],
        "from_agent": agents["planner"]["address"],
        "to_agent": agents["coder"]["address"],
        "action": "send",
        "subject": "Parent",
        "body": "x",
    })
    parent_id = send.json()["id"]
    await client.post("/messages/send", json={
        "agent_id": agents["coder"]["id"],
        "from_agent": agents["coder"]["address"],
        "to_agent": agents["planner"]["address"],
        "action": "reply",
        "subject": "Re: Parent",
        "body": "reply",
        "parent_id": parent_id,
    })
    r = await client.post(f"/admin/messages/{parent_id}/trash")
    assert r.status_code == 400


async def test_purge_single_message(client, agents):
    send = await client.post("/messages/send", json={
        "agent_id": agents["planner"]["id"],
        "from_agent": agents["planner"]["address"],
        "to_agent": agents["coder"]["address"],
        "action": "send",
        "subject": "To purge",
        "body": "x",
    })
    mid = send.json()["id"]
    await client.post(f"/admin/messages/{mid}/trash")
    r = await client.post(f"/admin/messages/{mid}/purge")
    assert r.status_code == 200
    listed = await client.get("/admin/trash/messages")
    assert listed.json() == []
    assert (await client.post(f"/admin/messages/{mid}/restore")).status_code == 404


# --- Admin Send ---

async def test_admin_send(client, agents):
    resp = await client.post("/admin/messages/send", json={
        "to_agent": agents["coder"]["address"],
        "subject": "Hello from human",
        "body": "Please do this task",
    })
    assert resp.status_code == 200
    msg = resp.json()
    assert msg["from_agent"] == _human_operator_address("testuser")
    assert msg["to_agent"] == agents["coder"]["address"]
    assert msg["action"] == "send"


async def test_admin_send_creates_human_operator(client, agents):
    await client.post("/admin/messages/send", json={
        "to_agent": agents["coder"]["address"],
        "subject": "Test",
        "body": "Body",
    })
    # human operator agent should exist — verify via admin stats
    resp = await client.get("/admin/agents/stats")
    addresses = {s["address"] for s in resp.json()}
    assert _human_operator_address("testuser") in addresses


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
        "to_agent": "nonexistent@testuser.amp.linkyun.co",
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
    assert "Trash" in resp.text


# --- Delete Agent ---

async def test_delete_agent(client, agents):
    agent_id = agents["coder"]["id"]
    resp = await client.delete(f"/admin/agents/{agent_id}")
    assert resp.status_code == 200
    assert resp.json()["agent_id"] == agent_id

    resp = await client.get(f"/agents/{agent_id}")
    assert resp.status_code == 404


async def test_delete_agent_not_found(client):
    resp = await client.delete("/admin/agents/nonexistent-id")
    assert resp.status_code == 404


async def test_delete_agent_preserves_messages(client, agents):
    """Deleting an agent should not remove its historical messages."""
    send_resp = await client.post("/messages/send", json={
        "agent_id": agents["planner"]["id"],
        "from_agent": agents["planner"]["address"],
        "to_agent": agents["coder"]["address"],
        "action": "send",
        "subject": "Task",
        "body": "Do this",
    })
    thread_id = send_resp.json()["thread_id"]
    agent_id = agents["coder"]["id"]
    resp = await client.delete(f"/admin/agents/{agent_id}")
    assert resp.status_code == 200

    # Messages still exist in the thread (planner agent still owns the thread)
    thread_resp = await client.get(f"/messages/thread/{thread_id}")
    assert thread_resp.status_code == 200
    assert len(thread_resp.json()) == 1


# --- Agent Tags ---

async def test_update_agent_tags(client, agents):
    agent_id = agents["coder"]["id"]
    resp = await client.put(
        f"/admin/agents/{agent_id}/tags",
        json={"tags": ["frontend", "python"]},
    )
    assert resp.status_code == 200
    assert resp.json()["tags"] == ["frontend", "python"]

    agent = await client.get(f"/agents/{agent_id}")
    assert agent.json()["tags"] == ["frontend", "python"]


async def test_update_agent_tags_not_found(client):
    resp = await client.put(
        "/admin/agents/nonexistent-id/tags",
        json={"tags": ["test"]},
    )
    assert resp.status_code == 404


async def test_agent_stats_include_tags(client, agents):
    agent_id = agents["planner"]["id"]
    await client.put(
        f"/admin/agents/{agent_id}/tags",
        json={"tags": ["lead", "planning"]},
    )
    resp = await client.get("/admin/agents/stats")
    assert resp.status_code == 200
    stats = resp.json()
    planner_stat = next(s for s in stats if s["agent_id"] == agent_id)
    assert planner_stat["tags"] == ["lead", "planning"]


async def test_register_agent_has_empty_tags(client):
    resp = await client.post("/agents/register", json={
        "name": "tagger", "role": "test",
        "system_prompt": "test prompt",
    })
    assert resp.status_code == 200
    assert resp.json()["tags"] == []
