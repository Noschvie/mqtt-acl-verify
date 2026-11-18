# SPDX-License-Identifier: AGPL-3.0-or-later
from mqtt_acl_verify.inventory import Direction
from mqtt_acl_verify.inventory.mosquitto import parse

LOG = """\
1700000000: New client connected from 10.0.0.5:51234 as DVES_1A2B3C (p2, c1, k30, u'kitchen').
1700000001: Received SUBSCRIBE from DVES_1A2B3C
1700000001: \tcmnd/kitchen/# (QoS 0)
1700000001: \tcmnd/tasmotas/# (QoS 0)
1700000001: DVES_1A2B3C 0 cmnd/kitchen/#
1700000001: Sending SUBACK to DVES_1A2B3C
1700000002: Received PUBLISH from DVES_1A2B3C (d0, q0, r1, m0, 'tele/kitchen/LWT', ... (6 bytes))
1700000003: Received PUBLISH from DVES_1A2B3C (d0, q0, r0, m0, 'tele/kitchen/STATE', ... (120 bytes))
1700000004: Received PUBLISH from DVES_1A2B3C (d0, q0, r0, m0, 'tele/kitchen/STATE', ... (120 bytes))
2026-11-18T21:00:00: Denied PUBLISH from DVES_1A2B3C (d0, q1, r0, m1, 'stat/other/POWER', ... (2 bytes))
"""


def test_parse_mosquitto_log():
    inv = parse(LOG.splitlines(keepends=True))
    rows = {(e.username, e.client_id, e.direction, e.topic): n for e, n in inv.entries()}
    assert rows[("kitchen", "DVES_1A2B3C", Direction.SUBSCRIBE, "cmnd/kitchen/#")] == 1
    assert rows[("kitchen", "DVES_1A2B3C", Direction.SUBSCRIBE, "cmnd/tasmotas/#")] == 1
    assert rows[("kitchen", "DVES_1A2B3C", Direction.PUBLISH, "tele/kitchen/STATE")] == 2
    assert rows[("kitchen", "DVES_1A2B3C", Direction.PUBLISH_DENIED, "stat/other/POWER")] == 1
    assert len(rows) == 5


def test_placeholders_and_grouping():
    inv = parse(LOG.splitlines()).with_placeholders().by_username()
    topics = {(e.direction, e.topic) for e, _ in inv.entries()}
    assert (Direction.SUBSCRIBE, "cmnd/%u/#") in topics
    assert (Direction.PUBLISH, "tele/%u/LWT") in topics
    assert (Direction.SUBSCRIBE, "cmnd/tasmotas/#") in topics


def test_csv_output():
    csv = parse(LOG.splitlines()).to_csv()
    assert csv.splitlines()[0] == "username,client_id,direction,topic,count"
