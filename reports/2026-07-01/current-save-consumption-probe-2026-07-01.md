# Current Save Consumption Probe

Scope: temporary copies of the current `isekai-farm` save; the real save is not modified.
Policy: this report records inventory consumption/decrement behavior only. No engine behavior is changed by this probe.

Summary: PASS=43 ISSUE=60 TOTAL=103

## Quantity Strategy Gap

Intended policy:

- High-risk or key inventory must be stored with exact quantity, unit, source, confidence, and location metadata before it can be spent automatically.
- Low-risk common consumables may be stored fuzzily, but the fuzzy value must still be structured, queryable, and usable by consumption rules.

Current implementation gap:

- The item table has only numeric `quantity` plus `unit` as first-class fields.
- Fuzzy inventory is usually parked in `details.quantity_text` or free-form properties.
- Render, query, validation, and decrement paths do not share one reliable fuzzy quantity representation.
- Ordinary fuzzy resources can be described, but cannot yet be consistently queried, reduced, exhausted, or escalated to an exact audit.
- High-risk resources already have campaign rules that demand precision, but the engine still needs stronger pre-commit guards against approximate or metadata-losing spends.

Tracking requirement: add a first-class quantity strategy that separates exact critical inventory from structured fuzzy low-risk consumables, with matching query, render, validation, and consumption behavior.

## Issue Summary

| Issue | Count |
|---|---:|
| `natural_consumption_misread_as_query` | 20 |
| `natural_consumption_not_ready` | 12 |
| `natural_consumption_committed_without_decrement` | 2 |
| `category_mutation_committed` | 1 |
| `consumed_item_upsert_mismatch_committed` | 1 |
| `consumption_noop_quantity_committed` | 1 |
| `durability_mutation_committed` | 1 |
| `equipped_slot_mutation_committed` | 1 |
| `minimal_high_risk_upsert_loses_metadata` | 1 |
| `minimal_upsert_loses_metadata` | 1 |
| `missing_unit_committed` | 1 |
| `name_mutation_committed` | 1 |
| `narrated_consumption_committed_without_decrement` | 1 |
| `natural_consumption_misread_as_maintenance` | 1 |
| `negative_consumed_quantity_committed` | 1 |
| `negative_quantity_written_or_reported_late` | 1 |
| `null_quantity_committed` | 1 |
| `payload_after_quantity_mismatch_committed` | 1 |
| `payload_before_quantity_mismatch_committed` | 1 |
| `payload_consumed_item_mismatch_committed` | 1 |
| `payload_consumed_quantity_mismatch_committed` | 1 |
| `properties_lost_committed` | 1 |
| `quality_mutation_committed` | 1 |
| `stackable_mutation_committed` | 1 |
| `stale_consumption_overwrites_quantity` | 1 |
| `status_mutation_committed` | 1 |
| `storage_location_lost_committed` | 1 |
| `unit_mismatch_committed` | 1 |
| `visibility_mutation_committed` | 1 |

## Issue By Area

| Area | Count |
|---|---:|
| natural consumption variants | 25 |
| guardrail extended | 19 |
| natural consumption | 10 |
| guardrail | 5 |
| stale write | 1 |

## Issues

| Area | Case | Observed | Expected | Issue |
|---|---|---|---|---|
| natural consumption | eat water spinach | start=query:entity can_proceed=True preview=query:ready ready=False before=13.0 after=13.0 committed=False ok=False | natural command should decrement item:v1-3a6b64e5c1 13->12 or block clearly before save | `natural_consumption_misread_as_query` |
| natural consumption | drink water | start=query:entity can_proceed=False preview=query:ready ready=False before=4.0 after=4.0 committed=False ok=False | natural command should decrement item:v1-0b81d0d73c 4->3.5 or block clearly before save | `natural_consumption_misread_as_query` |
| natural consumption | use salt | start=query:entity can_proceed=True preview=query:ready ready=False before=0.5 after=0.5 committed=False ok=False | natural command should decrement item:salt 0.5->0.25 or block clearly before save | `natural_consumption_misread_as_query` |
| natural consumption | use pine nut oil in cooking | start=action:craft can_proceed=True preview=craft:clarify ready=False before=3.0 after=3.0 committed=False ok=False | natural command should decrement item:pine-nut-oil 3->2.5 or block clearly before save | `natural_consumption_not_ready` |
| natural consumption | use black powder in fuse test | start=maintenance:maintenance can_proceed=True preview=maintenance:blocked ready=False before=0.5 after=0.5 committed=False ok=False | natural command should decrement item:black-powder 0.5->0.25 or block clearly before save | `natural_consumption_misread_as_maintenance` |
| natural consumption | use hemp fiber for rope | start=action:craft can_proceed=True preview=craft:clarify ready=False before=3.0 after=3.0 committed=False ok=False | natural command should decrement item:v1-9852b22696 3->2.5 or block clearly before save | `natural_consumption_not_ready` |
| natural consumption | shoot plain bolts in training | start=action:combat can_proceed=False preview=combat:clarify ready=False before=3.0 after=3.0 committed=False ok=False | natural command should decrement item:plain-bolts 3->0 or block clearly before save | `natural_consumption_not_ready` |
| natural consumption | shoot stun bolt natural complete | start=action:combat can_proceed=True preview=combat:clarify ready=False before=12.0 after=12.0 committed=False ok=False | natural command should decrement item:stun-thorn-bolts 12->11 or block clearly before save | `natural_consumption_not_ready` |
| natural consumption | shoot powder arrow natural complete | start=action:combat can_proceed=True preview=combat:clarify ready=False before=5.0 after=5.0 committed=False ok=False | natural command should decrement item:powder-arrows 5->4 or block clearly before save | `natural_consumption_not_ready` |
| natural consumption | feed t2 with fish | start=action:routine can_proceed=True preview=routine:ready ready=True before=0.0 after=0.0 committed=True ok=True | natural command should decrement item:turn-000043-small-fish 0->-1 or block clearly before save | `natural_consumption_committed_without_decrement` |
| natural consumption variants | sip water small amount | start=query:entity can_proceed=False preview=query:ready ready=False before=4.0 after=4.0 committed=False ok=False | natural command should decrement item:v1-0b81d0d73c 4->3.9 or block clearly before save | `natural_consumption_misread_as_query` |
| natural consumption variants | eat lettuce leaf | start=query:entity can_proceed=True preview=query:ready ready=False before=3.0 after=3.0 committed=False ok=False | natural command should decrement item:v1-f07d297448 3->2 or block clearly before save | `natural_consumption_misread_as_query` |
| natural consumption variants | eat amaranth leaves | start=query:entity can_proceed=True preview=query:ready ready=False before=8.0 after=8.0 committed=False ok=False | natural command should decrement item:v1-e267e90894 8->6 or block clearly before save | `natural_consumption_misread_as_query` |
| natural consumption variants | eat wild onion | start=query:entity can_proceed=True preview=query:ready ready=False before=3.0 after=3.0 committed=False ok=False | natural command should decrement item:v1-0629e81966 3->2 or block clearly before save | `natural_consumption_misread_as_query` |
| natural consumption variants | eat garlic leaf | start=query:entity can_proceed=True preview=query:ready ready=False before=2.0 after=2.0 committed=False ok=False | natural command should decrement item:v1-8aa915dbc4 2->1 or block clearly before save | `natural_consumption_misread_as_query` |
| natural consumption variants | eat chili | start=query:entity can_proceed=True preview=query:ready ready=False before=1.0 after=1.0 committed=False ok=False | natural command should decrement item:v1-d409c6757a 1->0 or block clearly before save | `natural_consumption_misread_as_query` |
| natural consumption variants | eat pine nuts | start=query:entity can_proceed=True preview=query:ready ready=False before=1.0 after=1.0 committed=False ok=False | natural command should decrement item:v1-b4fc16271b 1->0.5 or block clearly before save | `natural_consumption_misread_as_query` |
| natural consumption variants | cook with berries | start=action:craft can_proceed=True preview=craft:clarify ready=False before=0.5 after=0.5 committed=False ok=False | natural command should decrement item:v1-8182ae0835 0.5->0.25 or block clearly before save | `natural_consumption_not_ready` |
| natural consumption variants | use ordinary resin | start=action:craft can_proceed=True preview=craft:clarify ready=False before=0.5 after=0.5 committed=False ok=False | natural command should decrement item:v1-9bb88c5944 0.5->0.25 or block clearly before save | `natural_consumption_not_ready` |
| natural consumption variants | use hardened resin | start=query:entity can_proceed=True preview=query:ready ready=False before=80.0 after=80.0 committed=False ok=False | natural command should decrement item:v1-0322977645 80->70 or block clearly before save | `natural_consumption_misread_as_query` |
| natural consumption variants | use acid resin | start=query:entity can_proceed=True preview=query:ready ready=False before=30.0 after=30.0 committed=False ok=False | natural command should decrement item:v1-18a38459f1 30->25 or block clearly before save | `natural_consumption_misread_as_query` |
| natural consumption variants | use sulfur shards | start=query:entity can_proceed=True preview=query:ready ready=False before=1.0 after=1.0 committed=False ok=False | natural command should decrement item:v1-4681d8edfb 1->0.5 or block clearly before save | `natural_consumption_misread_as_query` |
| natural consumption variants | use niter needles | start=query:entity can_proceed=True preview=query:ready ready=False before=0.5 after=0.5 committed=False ok=False | natural command should decrement item:v1-26667819cb 0.5->0.25 or block clearly before save | `natural_consumption_misread_as_query` |
| natural consumption variants | use tung oil | start=query:entity can_proceed=True preview=query:ready ready=False before=1.0 after=1.0 committed=False ok=False | natural command should decrement item:v1-e247bca14a 1->0.75 or block clearly before save | `natural_consumption_misread_as_query` |
| natural consumption variants | use spare rope | start=query:entity can_proceed=True preview=query:ready ready=False before=3.0 after=3.0 committed=False ok=False | natural command should decrement item:v1-515c3e4a2f 3->2.5 or block clearly before save | `natural_consumption_misread_as_query` |
| natural consumption variants | use lake fiber | start=query:entity can_proceed=True preview=query:ready ready=False before=1.0 after=1.0 committed=False ok=False | natural command should decrement item:v1-ac25ff32a4 1->0.5 or block clearly before save | `natural_consumption_misread_as_query` |
| natural consumption variants | shoot old poison bolt | start=action:combat can_proceed=False preview=combat:clarify ready=False before=9.0 after=9.0 committed=False ok=False | natural command should decrement item:poison-bolts 9->8 or block clearly before save | `natural_consumption_not_ready` |
| natural consumption variants | shoot bamboo arrows | start=action:combat can_proceed=False preview=combat:clarify ready=False before=15.0 after=15.0 committed=False ok=False | natural command should decrement item:v1-9a74235657 15->10 or block clearly before save | `natural_consumption_not_ready` |
| natural consumption variants | shoot frost bolt | start=action:combat can_proceed=False preview=combat:clarify ready=False before=20.0 after=20.0 committed=False ok=False | natural command should decrement item:frost-thorn-bolts 20->19 or block clearly before save | `natural_consumption_not_ready` |
| natural consumption variants | shoot burst bolt | start=action:combat can_proceed=False preview=combat:clarify ready=False before=20.0 after=20.0 committed=False ok=False | natural command should decrement item:burst-thorn-bolts 20->19 or block clearly before save | `natural_consumption_not_ready` |
| natural consumption variants | shoot toxic thorn bolt | start=action:combat can_proceed=False preview=combat:clarify ready=False before=20.0 after=20.0 committed=False ok=False | natural command should decrement item:toxic-thorn-bolts 20->19 or block clearly before save | `natural_consumption_not_ready` |
| natural consumption variants | disassemble landmine | start=query:entity can_proceed=True preview=query:ready ready=False before=1.0 after=1.0 committed=False ok=False | natural command should decrement item:landmine-m2 1->0 or block clearly before save | `natural_consumption_misread_as_query` |
| natural consumption variants | feed with berries | start=action:routine can_proceed=True preview=routine:ready ready=True before=0.5 after=0.5 committed=True ok=True | natural command should decrement item:v1-8182ae0835 0.5->0.25 or block clearly before save | `natural_consumption_committed_without_decrement` |
| natural consumption variants | season meal with salt | start=query:entity can_proceed=True preview=query:ready ready=False before=0.5 after=0.5 committed=False ok=False | natural command should decrement item:salt 0.5->0.4 or block clearly before save | `natural_consumption_misread_as_query` |
| natural consumption variants | drink all water | start=query:entity can_proceed=True preview=query:ready ready=False before=4.0 after=4.0 committed=False ok=False | natural command should decrement item:v1-0b81d0d73c 4->0 or block clearly before save | `natural_consumption_misread_as_query` |
| guardrail | narrated consumption without upsert | before=13.0 after=13.0 committed=True ok=True | should block or remain uncommitted when consumption is not structured | `narrated_consumption_committed_without_decrement` |
| guardrail | event says consumed but upsert keeps same quantity | before=13.0 after=13.0 committed=True ok=True | should block inconsistent consumption/no-op quantity | `consumption_noop_quantity_committed` |
| guardrail | overconsume into negative quantity | before=0.5 after=-0.5 committed=True ok=False | negative inventory should be blocked before write and leave quantity unchanged | `negative_quantity_written_or_reported_late` |
| guardrail | unit mismatch on decrement | before=0.5 after=0.25支 committed=True ok=True | unit changes during pure consumption should be blocked | `unit_mismatch_committed` |
| guardrail | minimal quantity upsert preserves metadata | before_qty=5.0 after_qty=4.0 owner=pc:shenyan->None location=None->None properties_preserved=False committed=True ok=True | quantity decrements while owner/location/properties remain intact | `minimal_upsert_loses_metadata` |
| guardrail extended | null quantity on exact decrement | committed=True ok=True unchanged=False | should block null quantity when exact stock is decremented | `null_quantity_committed` |
| guardrail extended | missing unit on decrement | committed=True ok=True unchanged=False | should block losing unit during pure consumption | `missing_unit_committed` |
| guardrail extended | event consumes salt but upsert decrements water | committed=True ok=True unchanged=False | should block event/upsert item mismatch | `consumed_item_upsert_mismatch_committed` |
| guardrail extended | payload after quantity mismatches upsert | committed=True ok=True unchanged=False | should block payload after_quantity that disagrees with upsert quantity | `payload_after_quantity_mismatch_committed` |
| guardrail extended | payload before quantity mismatches db | committed=True ok=True unchanged=False | should block payload before_quantity that disagrees with current stock | `payload_before_quantity_mismatch_committed` |
| guardrail extended | payload consumed quantity too high | committed=True ok=True unchanged=False | should block consumed_quantity inconsistent with before/after | `payload_consumed_quantity_mismatch_committed` |
| guardrail extended | negative consumed quantity payload | committed=True ok=True unchanged=False | should block negative consumed_quantity in event payload | `negative_consumed_quantity_committed` |
| guardrail extended | payload consumed item id mismatch | committed=True ok=True unchanged=False | should block consumed_item_id that disagrees with upsert entity | `payload_consumed_item_mismatch_committed` |
| guardrail extended | category changed during decrement | committed=True ok=True unchanged=False | should block category mutation during pure consumption | `category_mutation_committed` |
| guardrail extended | quality changed during decrement | committed=True ok=True unchanged=False | should block quality mutation during pure consumption | `quality_mutation_committed` |
| guardrail extended | name changed during decrement | committed=True ok=True unchanged=False | should block renaming item during pure consumption | `name_mutation_committed` |
| guardrail extended | status archived during decrement | committed=True ok=True unchanged=False | should block status mutation during pure consumption | `status_mutation_committed` |
| guardrail extended | visibility hidden during decrement | committed=True ok=True unchanged=False | should block visibility mutation during pure consumption | `visibility_mutation_committed` |
| guardrail extended | location and owner lost during decrement | committed=True ok=True unchanged=False | should block dropping storage location/owner during pure consumption | `storage_location_lost_committed` |
| guardrail extended | properties lost during decrement | committed=True ok=True unchanged=False | should block losing high-risk item properties during pure consumption | `properties_lost_committed` |
| guardrail extended | stackable changed during decrement | committed=True ok=True unchanged=False | should block stackable mutation during pure consumption | `stackable_mutation_committed` |
| guardrail extended | durability changed during decrement | committed=True ok=True unchanged=False | should block durability mutation during pure consumption | `durability_mutation_committed` |
| guardrail extended | equipped slot changed during decrement | committed=True ok=True unchanged=False | should block equipped_slot mutation during pure consumption | `equipped_slot_mutation_committed` |
| guardrail extended | minimal toxic bolt upsert loses metadata | committed=True ok=True unchanged=False | should preserve owner/location/properties when decrementing high-risk ammo | `minimal_high_risk_upsert_loses_metadata` |
| stale write | stale consumption without expected_turn_id | initial_turn=turn:000044 after=0.4 first_ok=True stale_committed=True stale_ok=True | stale second consumption should not overwrite a fresher quantity | `stale_consumption_overwrites_quantity` |

## Full Matrix

| Status | Area | Case | Observed | Expected |
|---|---|---|---|---|
| PASS | auto combat | auto combat consumes stun bolt | before=12.0 after=11.0 committed=True ok=True | 12->11, commit ok |
| PASS | auto combat | auto combat consumes toxic bolt | before=20.0 after=19.0 committed=True ok=True | 20->19, commit ok |
| PASS | auto combat | auto combat consumes burst bolt | before=20.0 after=19.0 committed=True ok=True | 20->19, commit ok |
| PASS | auto combat | auto combat consumes frost bolt | before=20.0 after=19.0 committed=True ok=True | 20->19, commit ok |
| PASS | auto combat | auto combat consumes powder arrow | before=5.0 after=4.0 committed=True ok=True | 5->4, commit ok |
| PASS | auto combat | three sequential stun shots | before=12.0 after=9.0 outcomes=[True, True, True] | 12->9 across three committed shots |
| ISSUE | natural consumption | eat water spinach | start=query:entity can_proceed=True preview=query:ready ready=False before=13.0 after=13.0 committed=False ok=False | natural command should decrement item:v1-3a6b64e5c1 13->12 or block clearly before save |
| ISSUE | natural consumption | drink water | start=query:entity can_proceed=False preview=query:ready ready=False before=4.0 after=4.0 committed=False ok=False | natural command should decrement item:v1-0b81d0d73c 4->3.5 or block clearly before save |
| ISSUE | natural consumption | use salt | start=query:entity can_proceed=True preview=query:ready ready=False before=0.5 after=0.5 committed=False ok=False | natural command should decrement item:salt 0.5->0.25 or block clearly before save |
| ISSUE | natural consumption | use pine nut oil in cooking | start=action:craft can_proceed=True preview=craft:clarify ready=False before=3.0 after=3.0 committed=False ok=False | natural command should decrement item:pine-nut-oil 3->2.5 or block clearly before save |
| ISSUE | natural consumption | use black powder in fuse test | start=maintenance:maintenance can_proceed=True preview=maintenance:blocked ready=False before=0.5 after=0.5 committed=False ok=False | natural command should decrement item:black-powder 0.5->0.25 or block clearly before save |
| ISSUE | natural consumption | use hemp fiber for rope | start=action:craft can_proceed=True preview=craft:clarify ready=False before=3.0 after=3.0 committed=False ok=False | natural command should decrement item:v1-9852b22696 3->2.5 or block clearly before save |
| ISSUE | natural consumption | shoot plain bolts in training | start=action:combat can_proceed=False preview=combat:clarify ready=False before=3.0 after=3.0 committed=False ok=False | natural command should decrement item:plain-bolts 3->0 or block clearly before save |
| ISSUE | natural consumption | shoot stun bolt natural complete | start=action:combat can_proceed=True preview=combat:clarify ready=False before=12.0 after=12.0 committed=False ok=False | natural command should decrement item:stun-thorn-bolts 12->11 or block clearly before save |
| ISSUE | natural consumption | shoot powder arrow natural complete | start=action:combat can_proceed=True preview=combat:clarify ready=False before=5.0 after=5.0 committed=False ok=False | natural command should decrement item:powder-arrows 5->4 or block clearly before save |
| ISSUE | natural consumption | feed t2 with fish | start=action:routine can_proceed=True preview=routine:ready ready=True before=0.0 after=0.0 committed=True ok=True | natural command should decrement item:turn-000043-small-fish 0->-1 or block clearly before save |
| ISSUE | natural consumption variants | sip water small amount | start=query:entity can_proceed=False preview=query:ready ready=False before=4.0 after=4.0 committed=False ok=False | natural command should decrement item:v1-0b81d0d73c 4->3.9 or block clearly before save |
| ISSUE | natural consumption variants | eat lettuce leaf | start=query:entity can_proceed=True preview=query:ready ready=False before=3.0 after=3.0 committed=False ok=False | natural command should decrement item:v1-f07d297448 3->2 or block clearly before save |
| ISSUE | natural consumption variants | eat amaranth leaves | start=query:entity can_proceed=True preview=query:ready ready=False before=8.0 after=8.0 committed=False ok=False | natural command should decrement item:v1-e267e90894 8->6 or block clearly before save |
| ISSUE | natural consumption variants | eat wild onion | start=query:entity can_proceed=True preview=query:ready ready=False before=3.0 after=3.0 committed=False ok=False | natural command should decrement item:v1-0629e81966 3->2 or block clearly before save |
| ISSUE | natural consumption variants | eat garlic leaf | start=query:entity can_proceed=True preview=query:ready ready=False before=2.0 after=2.0 committed=False ok=False | natural command should decrement item:v1-8aa915dbc4 2->1 or block clearly before save |
| ISSUE | natural consumption variants | eat chili | start=query:entity can_proceed=True preview=query:ready ready=False before=1.0 after=1.0 committed=False ok=False | natural command should decrement item:v1-d409c6757a 1->0 or block clearly before save |
| ISSUE | natural consumption variants | eat pine nuts | start=query:entity can_proceed=True preview=query:ready ready=False before=1.0 after=1.0 committed=False ok=False | natural command should decrement item:v1-b4fc16271b 1->0.5 or block clearly before save |
| ISSUE | natural consumption variants | cook with berries | start=action:craft can_proceed=True preview=craft:clarify ready=False before=0.5 after=0.5 committed=False ok=False | natural command should decrement item:v1-8182ae0835 0.5->0.25 or block clearly before save |
| ISSUE | natural consumption variants | use ordinary resin | start=action:craft can_proceed=True preview=craft:clarify ready=False before=0.5 after=0.5 committed=False ok=False | natural command should decrement item:v1-9bb88c5944 0.5->0.25 or block clearly before save |
| ISSUE | natural consumption variants | use hardened resin | start=query:entity can_proceed=True preview=query:ready ready=False before=80.0 after=80.0 committed=False ok=False | natural command should decrement item:v1-0322977645 80->70 or block clearly before save |
| ISSUE | natural consumption variants | use acid resin | start=query:entity can_proceed=True preview=query:ready ready=False before=30.0 after=30.0 committed=False ok=False | natural command should decrement item:v1-18a38459f1 30->25 or block clearly before save |
| ISSUE | natural consumption variants | use sulfur shards | start=query:entity can_proceed=True preview=query:ready ready=False before=1.0 after=1.0 committed=False ok=False | natural command should decrement item:v1-4681d8edfb 1->0.5 or block clearly before save |
| ISSUE | natural consumption variants | use niter needles | start=query:entity can_proceed=True preview=query:ready ready=False before=0.5 after=0.5 committed=False ok=False | natural command should decrement item:v1-26667819cb 0.5->0.25 or block clearly before save |
| ISSUE | natural consumption variants | use tung oil | start=query:entity can_proceed=True preview=query:ready ready=False before=1.0 after=1.0 committed=False ok=False | natural command should decrement item:v1-e247bca14a 1->0.75 or block clearly before save |
| ISSUE | natural consumption variants | use spare rope | start=query:entity can_proceed=True preview=query:ready ready=False before=3.0 after=3.0 committed=False ok=False | natural command should decrement item:v1-515c3e4a2f 3->2.5 or block clearly before save |
| ISSUE | natural consumption variants | use lake fiber | start=query:entity can_proceed=True preview=query:ready ready=False before=1.0 after=1.0 committed=False ok=False | natural command should decrement item:v1-ac25ff32a4 1->0.5 or block clearly before save |
| ISSUE | natural consumption variants | shoot old poison bolt | start=action:combat can_proceed=False preview=combat:clarify ready=False before=9.0 after=9.0 committed=False ok=False | natural command should decrement item:poison-bolts 9->8 or block clearly before save |
| ISSUE | natural consumption variants | shoot bamboo arrows | start=action:combat can_proceed=False preview=combat:clarify ready=False before=15.0 after=15.0 committed=False ok=False | natural command should decrement item:v1-9a74235657 15->10 or block clearly before save |
| ISSUE | natural consumption variants | shoot frost bolt | start=action:combat can_proceed=False preview=combat:clarify ready=False before=20.0 after=20.0 committed=False ok=False | natural command should decrement item:frost-thorn-bolts 20->19 or block clearly before save |
| ISSUE | natural consumption variants | shoot burst bolt | start=action:combat can_proceed=False preview=combat:clarify ready=False before=20.0 after=20.0 committed=False ok=False | natural command should decrement item:burst-thorn-bolts 20->19 or block clearly before save |
| ISSUE | natural consumption variants | shoot toxic thorn bolt | start=action:combat can_proceed=False preview=combat:clarify ready=False before=20.0 after=20.0 committed=False ok=False | natural command should decrement item:toxic-thorn-bolts 20->19 or block clearly before save |
| ISSUE | natural consumption variants | disassemble landmine | start=query:entity can_proceed=True preview=query:ready ready=False before=1.0 after=1.0 committed=False ok=False | natural command should decrement item:landmine-m2 1->0 or block clearly before save |
| ISSUE | natural consumption variants | feed with berries | start=action:routine can_proceed=True preview=routine:ready ready=True before=0.5 after=0.5 committed=True ok=True | natural command should decrement item:v1-8182ae0835 0.5->0.25 or block clearly before save |
| ISSUE | natural consumption variants | season meal with salt | start=query:entity can_proceed=True preview=query:ready ready=False before=0.5 after=0.5 committed=False ok=False | natural command should decrement item:salt 0.5->0.4 or block clearly before save |
| ISSUE | natural consumption variants | drink all water | start=query:entity can_proceed=True preview=query:ready ready=False before=4.0 after=4.0 committed=False ok=False | natural command should decrement item:v1-0b81d0d73c 4->0 or block clearly before save |
| PASS | manual consumption | consume one water spinach | before=13.0 after=12.0 committed=True ok=True health=True | quantity becomes 12, commit ok, health ok |
| PASS | manual consumption | consume fractional salt | before=0.5 after=0.25 committed=True ok=True health=True | quantity becomes 0.25, commit ok, health ok |
| PASS | manual consumption | drink half liter water | before=4.0 after=3.5 committed=True ok=True health=True | quantity becomes 3.5, commit ok, health ok |
| PASS | manual consumption | use pine nut oil | before=3.0 after=2.5 committed=True ok=True health=True | quantity becomes 2.5, commit ok, health ok |
| PASS | manual consumption | use black powder | before=0.5 after=0.25 committed=True ok=True health=True | quantity becomes 0.25, commit ok, health ok |
| PASS | manual consumption | use hemp fiber | before=3.0 after=2.5 committed=True ok=True health=True | quantity becomes 2.5, commit ok, health ok |
| PASS | manual consumption | use milky residue | before=40.0 after=30.0 committed=True ok=True health=True | quantity becomes 30, commit ok, health ok |
| PASS | manual consumption | consume single purple leaf | before=1.0 after=0.0 committed=True ok=True health=True | quantity becomes 0, commit ok, health ok |
| PASS | manual consumption | consume all plain bolts | before=3.0 after=0.0 committed=True ok=True health=True | quantity becomes 0, commit ok, health ok |
| PASS | manual consumption | manual ammo decrement | before=12.0 after=11.0 committed=True ok=True health=True | quantity becomes 11, commit ok, health ok |
| PASS | manual consumption extended | manual lettuce leaf | before=3.0 after=2.0 committed=True ok=True health=True query_ok=True | quantity becomes 2, query updates immediately, health ok |
| PASS | manual consumption extended | manual amaranth leaves | before=8.0 after=6.0 committed=True ok=True health=True query_ok=True | quantity becomes 6, query updates immediately, health ok |
| PASS | manual consumption extended | manual wild onion | before=3.0 after=2.0 committed=True ok=True health=True query_ok=True | quantity becomes 2, query updates immediately, health ok |
| PASS | manual consumption extended | manual garlic leaf | before=2.0 after=1.0 committed=True ok=True health=True query_ok=True | quantity becomes 1, query updates immediately, health ok |
| PASS | manual consumption extended | manual red chili | before=1.0 after=0.0 committed=True ok=True health=True query_ok=True | quantity becomes 0, query updates immediately, health ok |
| PASS | manual consumption extended | manual red berries | before=0.5 after=0.25 committed=True ok=True health=True query_ok=True | quantity becomes 0.25, query updates immediately, health ok |
| PASS | manual consumption extended | manual pine nuts | before=1.0 after=0.5 committed=True ok=True health=True query_ok=True | quantity becomes 0.5, query updates immediately, health ok |
| PASS | manual consumption extended | manual ordinary resin | before=0.5 after=0.25 committed=True ok=True health=True query_ok=True | quantity becomes 0.25, query updates immediately, health ok |
| PASS | manual consumption extended | manual hardened resin | before=80.0 after=70.0 committed=True ok=True health=True query_ok=True | quantity becomes 70, query updates immediately, health ok |
| PASS | manual consumption extended | manual acid resin | before=30.0 after=25.0 committed=True ok=True health=True query_ok=True | quantity becomes 25, query updates immediately, health ok |
| PASS | manual consumption extended | manual sulfur shards | before=1.0 after=0.5 committed=True ok=True health=True query_ok=True | quantity becomes 0.5, query updates immediately, health ok |
| PASS | manual consumption extended | manual niter needles | before=0.5 after=0.25 committed=True ok=True health=True query_ok=True | quantity becomes 0.25, query updates immediately, health ok |
| PASS | manual consumption extended | manual tung oil | before=1.0 after=0.75 committed=True ok=True health=True query_ok=True | quantity becomes 0.75, query updates immediately, health ok |
| PASS | manual consumption extended | manual spare rope | before=3.0 after=2.5 committed=True ok=True health=True query_ok=True | quantity becomes 2.5, query updates immediately, health ok |
| PASS | manual consumption extended | manual lake fiber | before=1.0 after=0.5 committed=True ok=True health=True query_ok=True | quantity becomes 0.5, query updates immediately, health ok |
| PASS | manual consumption extended | manual old poison bolt | before=9.0 after=8.0 committed=True ok=True health=True query_ok=True | quantity becomes 8, query updates immediately, health ok |
| PASS | manual consumption extended | manual bamboo arrows | before=15.0 after=10.0 committed=True ok=True health=True query_ok=True | quantity becomes 10, query updates immediately, health ok |
| PASS | manual consumption extended | manual frost bolt | before=20.0 after=19.0 committed=True ok=True health=True query_ok=True | quantity becomes 19, query updates immediately, health ok |
| PASS | manual consumption extended | manual burst bolt | before=20.0 after=19.0 committed=True ok=True health=True query_ok=True | quantity becomes 19, query updates immediately, health ok |
| PASS | manual consumption extended | manual toxic bolt | before=20.0 after=19.0 committed=True ok=True health=True query_ok=True | quantity becomes 19, query updates immediately, health ok |
| PASS | manual consumption extended | manual plain bolt partial | before=3.0 after=2.0 committed=True ok=True health=True query_ok=True | quantity becomes 2, query updates immediately, health ok |
| PASS | manual consumption extended | manual landmine removed | before=1.0 after=0.0 committed=True ok=True health=True query_ok=True | quantity becomes 0, query updates immediately, health ok |
| PASS | manual consumption extended | manual bamboo water all | before=4.0 after=0.0 committed=True ok=True health=True query_ok=True | quantity becomes 0, query updates immediately, health ok |
| PASS | manual consumption extended | manual berry vinegar | before=1.0 after=0.5 committed=True ok=True health=True query_ok=True | quantity becomes 0.5, query updates immediately, health ok |
| PASS | manual consumption extended | manual sulfur sample | before=1.0 after=0.0 committed=True ok=True health=True query_ok=True | quantity becomes 0, query updates immediately, health ok |
| ISSUE | guardrail | narrated consumption without upsert | before=13.0 after=13.0 committed=True ok=True | should block or remain uncommitted when consumption is not structured |
| ISSUE | guardrail | event says consumed but upsert keeps same quantity | before=13.0 after=13.0 committed=True ok=True | should block inconsistent consumption/no-op quantity |
| ISSUE | guardrail | overconsume into negative quantity | before=0.5 after=-0.5 committed=True ok=False | negative inventory should be blocked before write and leave quantity unchanged |
| ISSUE | guardrail | unit mismatch on decrement | before=0.5 after=0.25支 committed=True ok=True | unit changes during pure consumption should be blocked |
| ISSUE | guardrail | minimal quantity upsert preserves metadata | before_qty=5.0 after_qty=4.0 owner=pc:shenyan->None location=None->None properties_preserved=False committed=True ok=True | quantity decrements while owner/location/properties remain intact |
| PASS | guardrail extended | non-numeric quantity on decrement | committed=False ok=False unchanged=True | should block non-numeric quantity before write |
| ISSUE | guardrail extended | null quantity on exact decrement | committed=True ok=True unchanged=False | should block null quantity when exact stock is decremented |
| ISSUE | guardrail extended | missing unit on decrement | committed=True ok=True unchanged=False | should block losing unit during pure consumption |
| ISSUE | guardrail extended | event consumes salt but upsert decrements water | committed=True ok=True unchanged=False | should block event/upsert item mismatch |
| ISSUE | guardrail extended | payload after quantity mismatches upsert | committed=True ok=True unchanged=False | should block payload after_quantity that disagrees with upsert quantity |
| ISSUE | guardrail extended | payload before quantity mismatches db | committed=True ok=True unchanged=False | should block payload before_quantity that disagrees with current stock |
| ISSUE | guardrail extended | payload consumed quantity too high | committed=True ok=True unchanged=False | should block consumed_quantity inconsistent with before/after |
| ISSUE | guardrail extended | negative consumed quantity payload | committed=True ok=True unchanged=False | should block negative consumed_quantity in event payload |
| ISSUE | guardrail extended | payload consumed item id mismatch | committed=True ok=True unchanged=False | should block consumed_item_id that disagrees with upsert entity |
| ISSUE | guardrail extended | category changed during decrement | committed=True ok=True unchanged=False | should block category mutation during pure consumption |
| ISSUE | guardrail extended | quality changed during decrement | committed=True ok=True unchanged=False | should block quality mutation during pure consumption |
| ISSUE | guardrail extended | name changed during decrement | committed=True ok=True unchanged=False | should block renaming item during pure consumption |
| ISSUE | guardrail extended | status archived during decrement | committed=True ok=True unchanged=False | should block status mutation during pure consumption |
| ISSUE | guardrail extended | visibility hidden during decrement | committed=True ok=True unchanged=False | should block visibility mutation during pure consumption |
| ISSUE | guardrail extended | location and owner lost during decrement | committed=True ok=True unchanged=False | should block dropping storage location/owner during pure consumption |
| ISSUE | guardrail extended | properties lost during decrement | committed=True ok=True unchanged=False | should block losing high-risk item properties during pure consumption |
| ISSUE | guardrail extended | stackable changed during decrement | committed=True ok=True unchanged=False | should block stackable mutation during pure consumption |
| ISSUE | guardrail extended | durability changed during decrement | committed=True ok=True unchanged=False | should block durability mutation during pure consumption |
| ISSUE | guardrail extended | equipped slot changed during decrement | committed=True ok=True unchanged=False | should block equipped_slot mutation during pure consumption |
| ISSUE | guardrail extended | minimal toxic bolt upsert loses metadata | committed=True ok=True unchanged=False | should preserve owner/location/properties when decrementing high-risk ammo |
| ISSUE | stale write | stale consumption without expected_turn_id | initial_turn=turn:000044 after=0.4 first_ok=True stale_committed=True stale_ok=True | stale second consumption should not overwrite a fresher quantity |
| PASS | stale write | stale consumption with expected_turn_id | initial_turn=turn:000044 after=0.25 first_ok=True stale_committed=False error=ValueError: stale write: expected current turn turn:000044, actual turn:000045 | expected_turn_id should block stale write and preserve 0.25 |

## Details

### PASS · auto combat · auto combat consumes stun bolt

- Observed: before=12.0 after=11.0 committed=True ok=True
- Expected: 12->11, commit ok
- state_audit=HIGH_RISK_ITEM_METADATA_INCOMPLETE

### PASS · auto combat · auto combat consumes toxic bolt

- Observed: before=20.0 after=19.0 committed=True ok=True
- Expected: 20->19, commit ok
- state_audit=HIGH_RISK_ITEM_METADATA_INCOMPLETE

### PASS · auto combat · auto combat consumes burst bolt

- Observed: before=20.0 after=19.0 committed=True ok=True
- Expected: 20->19, commit ok
- state_audit=HIGH_RISK_ITEM_METADATA_INCOMPLETE

### PASS · auto combat · auto combat consumes frost bolt

- Observed: before=20.0 after=19.0 committed=True ok=True
- Expected: 20->19, commit ok
- state_audit=HIGH_RISK_ITEM_METADATA_INCOMPLETE

### PASS · auto combat · auto combat consumes powder arrow

- Observed: before=5.0 after=4.0 committed=True ok=True
- Expected: 5->4, commit ok
- state_audit=HIGH_RISK_ITEM_METADATA_INCOMPLETE

### PASS · auto combat · three sequential stun shots

- Observed: before=12.0 after=9.0 outcomes=[True, True, True]
- Expected: 12->9 across three committed shots
- state_audit=HIGH_RISK_ITEM_METADATA_INCOMPLETE
- state_audit=HIGH_RISK_ITEM_METADATA_INCOMPLETE
- state_audit=HIGH_RISK_ITEM_METADATA_INCOMPLETE

### ISSUE · natural consumption · eat water spinach

- Observed: start=query:entity can_proceed=True preview=query:ready ready=False before=13.0 after=13.0 committed=False ok=False
- Expected: natural command should decrement item:v1-3a6b64e5c1 13->12 or block clearly before save
- Issue: `natural_consumption_misread_as_query`
- player_message=这是只读查询请求，不需要行动预演或保存。
- errors=[]
- warnings=[]
- 

### ISSUE · natural consumption · drink water

- Observed: start=query:entity can_proceed=False preview=query:ready ready=False before=4.0 after=4.0 committed=False ok=False
- Expected: natural command should decrement item:v1-0b81d0d73c 4->3.5 or block clearly before save
- Issue: `natural_consumption_misread_as_query`
- player_message=这是只读查询请求，不需要行动预演或保存。
- errors=[]
- warnings=[]
- 

### ISSUE · natural consumption · use salt

- Observed: start=query:entity can_proceed=True preview=query:ready ready=False before=0.5 after=0.5 committed=False ok=False
- Expected: natural command should decrement item:salt 0.5->0.25 or block clearly before save
- Issue: `natural_consumption_misread_as_query`
- player_message=这是只读查询请求，不需要行动预演或保存。
- errors=[]
- warnings=[]
- 

### ISSUE · natural consumption · use pine nut oil in cooking

- Observed: start=action:craft can_proceed=True preview=craft:clarify ready=False before=3.0 after=3.0 committed=False ok=False
- Expected: natural command should decrement item:pine-nut-oil 3->2.5 or block clearly before save
- Issue: `natural_consumption_not_ready`
- player_message=现在还不能可靠完成 目标成品。需要先补齐材料、配方、耗时或成品定义。
- errors=['目标成品未指定：必须明确成品名称、数量、品质和用途。', '材料未指定：保存前必须列出材料、工具、消耗量和剩余量。', '未匹配结构化配方：保存前必须手动确认输入、输出和失败代价。', '耗时未指定：需要估算制作占用的时段和体力。']
- warnings=[]
- 

### ISSUE · natural consumption · use black powder in fuse test

- Observed: start=maintenance:maintenance can_proceed=True preview=maintenance:blocked ready=False before=0.5 after=0.5 committed=False ok=False
- Expected: natural command should decrement item:black-powder 0.5->0.25 or block clearly before save
- Issue: `natural_consumption_misread_as_maintenance`
- player_message=这是维护或作者工具请求，不会作为普通玩家回合预演。
- errors=[]
- warnings=['maintenance request is outside the player turn profile']
- 

### ISSUE · natural consumption · use hemp fiber for rope

- Observed: start=action:craft can_proceed=True preview=craft:clarify ready=False before=3.0 after=3.0 committed=False ok=False
- Expected: natural command should decrement item:v1-9852b22696 3->2.5 or block clearly before save
- Issue: `natural_consumption_not_ready`
- player_message=现在还不能可靠完成 目标成品。需要先补齐材料、配方、耗时或成品定义。
- errors=['目标成品未指定：必须明确成品名称、数量、品质和用途。', '材料未指定：保存前必须列出材料、工具、消耗量和剩余量。', '未匹配结构化配方：保存前必须手动确认输入、输出和失败代价。', '耗时未指定：需要估算制作占用的时段和体力。']
- warnings=[]
- 

### ISSUE · natural consumption · shoot plain bolts in training

- Observed: start=action:combat can_proceed=False preview=combat:clarify ready=False before=3.0 after=3.0 committed=False ok=False
- Expected: natural command should decrement item:plain-bolts 3->0 or block clearly before save
- Issue: `natural_consumption_not_ready`
- player_message=还需要补充 target, weapon, ammo, distance，我才能可靠结算这次 combat。
- errors=['目标未明确：需要目标实体或清楚的场景目标。', '距离未明确：需要至少给出贴身/近距/标准/远距或步数。', '弹药未明确：射击前必须选择弹药。', '武器未明确：保存前必须指定武器，不能由引擎默认选择。']
- warnings=[]
- 

### ISSUE · natural consumption · shoot stun bolt natural complete

- Observed: start=action:combat can_proceed=True preview=combat:clarify ready=False before=12.0 after=12.0 committed=False ok=False
- Expected: natural command should decrement item:stun-thorn-bolts 12->11 or block clearly before save
- Issue: `natural_consumption_not_ready`
- player_message=还需要补充 target, weapon, ammo, distance，我才能可靠结算这次 combat。
- errors=['目标未明确：需要目标实体或清楚的场景目标。', '距离未明确：需要至少给出贴身/近距/标准/远距或步数。', '弹药未明确：射击前必须选择弹药。', '武器未明确：保存前必须指定武器，不能由引擎默认选择。']
- warnings=[]
- 

### ISSUE · natural consumption · shoot powder arrow natural complete

- Observed: start=action:combat can_proceed=True preview=combat:clarify ready=False before=5.0 after=5.0 committed=False ok=False
- Expected: natural command should decrement item:powder-arrows 5->4 or block clearly before save
- Issue: `natural_consumption_not_ready`
- player_message=还需要补充 target, weapon, ammo, distance，我才能可靠结算这次 combat。
- errors=['目标未明确：需要目标实体或清楚的场景目标。', '距离未明确：需要至少给出贴身/近距/标准/远距或步数。', '弹药未明确：射击前必须选择弹药。', '武器未明确：保存前必须指定武器，不能由引擎默认选择。']
- warnings=[]
- 

### ISSUE · natural consumption · feed t2 with fish

- Observed: start=action:routine can_proceed=True preview=routine:ready ready=True before=0.0 after=0.0 committed=True ok=True
- Expected: natural command should decrement item:turn-000043-small-fish 0->-1 or block clearly before save
- Issue: `natural_consumption_committed_without_decrement`
- player_message=已识别为日常维护。这是低风险 routine，不会自动制造资源、推进关系或创建新事实。
- errors=[]
- warnings=[]
- 

### ISSUE · natural consumption variants · sip water small amount

- Observed: start=query:entity can_proceed=False preview=query:ready ready=False before=4.0 after=4.0 committed=False ok=False
- Expected: natural command should decrement item:v1-0b81d0d73c 4->3.9 or block clearly before save
- Issue: `natural_consumption_misread_as_query`
- player_message=这是只读查询请求，不需要行动预演或保存。
- errors=[]
- warnings=[]
- 

### ISSUE · natural consumption variants · eat lettuce leaf

- Observed: start=query:entity can_proceed=True preview=query:ready ready=False before=3.0 after=3.0 committed=False ok=False
- Expected: natural command should decrement item:v1-f07d297448 3->2 or block clearly before save
- Issue: `natural_consumption_misread_as_query`
- player_message=这是只读查询请求，不需要行动预演或保存。
- errors=[]
- warnings=[]
- 

### ISSUE · natural consumption variants · eat amaranth leaves

- Observed: start=query:entity can_proceed=True preview=query:ready ready=False before=8.0 after=8.0 committed=False ok=False
- Expected: natural command should decrement item:v1-e267e90894 8->6 or block clearly before save
- Issue: `natural_consumption_misread_as_query`
- player_message=这是只读查询请求，不需要行动预演或保存。
- errors=[]
- warnings=[]
- 

### ISSUE · natural consumption variants · eat wild onion

- Observed: start=query:entity can_proceed=True preview=query:ready ready=False before=3.0 after=3.0 committed=False ok=False
- Expected: natural command should decrement item:v1-0629e81966 3->2 or block clearly before save
- Issue: `natural_consumption_misread_as_query`
- player_message=这是只读查询请求，不需要行动预演或保存。
- errors=[]
- warnings=[]
- 

### ISSUE · natural consumption variants · eat garlic leaf

- Observed: start=query:entity can_proceed=True preview=query:ready ready=False before=2.0 after=2.0 committed=False ok=False
- Expected: natural command should decrement item:v1-8aa915dbc4 2->1 or block clearly before save
- Issue: `natural_consumption_misread_as_query`
- player_message=这是只读查询请求，不需要行动预演或保存。
- errors=[]
- warnings=[]
- 

### ISSUE · natural consumption variants · eat chili

- Observed: start=query:entity can_proceed=True preview=query:ready ready=False before=1.0 after=1.0 committed=False ok=False
- Expected: natural command should decrement item:v1-d409c6757a 1->0 or block clearly before save
- Issue: `natural_consumption_misread_as_query`
- player_message=这是只读查询请求，不需要行动预演或保存。
- errors=[]
- warnings=[]
- 

### ISSUE · natural consumption variants · eat pine nuts

- Observed: start=query:entity can_proceed=True preview=query:ready ready=False before=1.0 after=1.0 committed=False ok=False
- Expected: natural command should decrement item:v1-b4fc16271b 1->0.5 or block clearly before save
- Issue: `natural_consumption_misread_as_query`
- player_message=这是只读查询请求，不需要行动预演或保存。
- errors=[]
- warnings=[]
- 

### ISSUE · natural consumption variants · cook with berries

- Observed: start=action:craft can_proceed=True preview=craft:clarify ready=False before=0.5 after=0.5 committed=False ok=False
- Expected: natural command should decrement item:v1-8182ae0835 0.5->0.25 or block clearly before save
- Issue: `natural_consumption_not_ready`
- player_message=现在还不能可靠完成 目标成品。需要先补齐材料、配方、耗时或成品定义。
- errors=['目标成品未指定：必须明确成品名称、数量、品质和用途。', '材料未指定：保存前必须列出材料、工具、消耗量和剩余量。', '未匹配结构化配方：保存前必须手动确认输入、输出和失败代价。', '耗时未指定：需要估算制作占用的时段和体力。']
- warnings=[]
- 

### ISSUE · natural consumption variants · use ordinary resin

- Observed: start=action:craft can_proceed=True preview=craft:clarify ready=False before=0.5 after=0.5 committed=False ok=False
- Expected: natural command should decrement item:v1-9bb88c5944 0.5->0.25 or block clearly before save
- Issue: `natural_consumption_not_ready`
- player_message=现在还不能可靠完成 目标成品。需要先补齐材料、配方、耗时或成品定义。
- errors=['目标成品未指定：必须明确成品名称、数量、品质和用途。', '材料未指定：保存前必须列出材料、工具、消耗量和剩余量。', '未匹配结构化配方：保存前必须手动确认输入、输出和失败代价。', '耗时未指定：需要估算制作占用的时段和体力。']
- warnings=[]
- 

### ISSUE · natural consumption variants · use hardened resin

- Observed: start=query:entity can_proceed=True preview=query:ready ready=False before=80.0 after=80.0 committed=False ok=False
- Expected: natural command should decrement item:v1-0322977645 80->70 or block clearly before save
- Issue: `natural_consumption_misread_as_query`
- player_message=这是只读查询请求，不需要行动预演或保存。
- errors=[]
- warnings=[]
- 

### ISSUE · natural consumption variants · use acid resin

- Observed: start=query:entity can_proceed=True preview=query:ready ready=False before=30.0 after=30.0 committed=False ok=False
- Expected: natural command should decrement item:v1-18a38459f1 30->25 or block clearly before save
- Issue: `natural_consumption_misread_as_query`
- player_message=这是只读查询请求，不需要行动预演或保存。
- errors=[]
- warnings=[]
- 

### ISSUE · natural consumption variants · use sulfur shards

- Observed: start=query:entity can_proceed=True preview=query:ready ready=False before=1.0 after=1.0 committed=False ok=False
- Expected: natural command should decrement item:v1-4681d8edfb 1->0.5 or block clearly before save
- Issue: `natural_consumption_misread_as_query`
- player_message=这是只读查询请求，不需要行动预演或保存。
- errors=[]
- warnings=[]
- 

### ISSUE · natural consumption variants · use niter needles

- Observed: start=query:entity can_proceed=True preview=query:ready ready=False before=0.5 after=0.5 committed=False ok=False
- Expected: natural command should decrement item:v1-26667819cb 0.5->0.25 or block clearly before save
- Issue: `natural_consumption_misread_as_query`
- player_message=这是只读查询请求，不需要行动预演或保存。
- errors=[]
- warnings=[]
- 

### ISSUE · natural consumption variants · use tung oil

- Observed: start=query:entity can_proceed=True preview=query:ready ready=False before=1.0 after=1.0 committed=False ok=False
- Expected: natural command should decrement item:v1-e247bca14a 1->0.75 or block clearly before save
- Issue: `natural_consumption_misread_as_query`
- player_message=这是只读查询请求，不需要行动预演或保存。
- errors=[]
- warnings=[]
- 

### ISSUE · natural consumption variants · use spare rope

- Observed: start=query:entity can_proceed=True preview=query:ready ready=False before=3.0 after=3.0 committed=False ok=False
- Expected: natural command should decrement item:v1-515c3e4a2f 3->2.5 or block clearly before save
- Issue: `natural_consumption_misread_as_query`
- player_message=这是只读查询请求，不需要行动预演或保存。
- errors=[]
- warnings=[]
- 

### ISSUE · natural consumption variants · use lake fiber

- Observed: start=query:entity can_proceed=True preview=query:ready ready=False before=1.0 after=1.0 committed=False ok=False
- Expected: natural command should decrement item:v1-ac25ff32a4 1->0.5 or block clearly before save
- Issue: `natural_consumption_misread_as_query`
- player_message=这是只读查询请求，不需要行动预演或保存。
- errors=[]
- warnings=[]
- 

### ISSUE · natural consumption variants · shoot old poison bolt

- Observed: start=action:combat can_proceed=False preview=combat:clarify ready=False before=9.0 after=9.0 committed=False ok=False
- Expected: natural command should decrement item:poison-bolts 9->8 or block clearly before save
- Issue: `natural_consumption_not_ready`
- player_message=还需要补充 target, weapon, ammo, distance，我才能可靠结算这次 combat。
- errors=['目标未明确：需要目标实体或清楚的场景目标。', '距离未明确：需要至少给出贴身/近距/标准/远距或步数。', '弹药未明确：射击前必须选择弹药。', '武器未明确：保存前必须指定武器，不能由引擎默认选择。']
- warnings=[]
- 

### ISSUE · natural consumption variants · shoot bamboo arrows

- Observed: start=action:combat can_proceed=False preview=combat:clarify ready=False before=15.0 after=15.0 committed=False ok=False
- Expected: natural command should decrement item:v1-9a74235657 15->10 or block clearly before save
- Issue: `natural_consumption_not_ready`
- player_message=还需要补充 target, weapon, ammo, distance，我才能可靠结算这次 combat。
- errors=['目标未明确：需要目标实体或清楚的场景目标。', '距离未明确：需要至少给出贴身/近距/标准/远距或步数。', '弹药未明确：射击前必须选择弹药。', '武器未明确：保存前必须指定武器，不能由引擎默认选择。']
- warnings=[]
- 

### ISSUE · natural consumption variants · shoot frost bolt

- Observed: start=action:combat can_proceed=False preview=combat:clarify ready=False before=20.0 after=20.0 committed=False ok=False
- Expected: natural command should decrement item:frost-thorn-bolts 20->19 or block clearly before save
- Issue: `natural_consumption_not_ready`
- player_message=还需要补充 target, weapon, ammo, distance，我才能可靠结算这次 combat。
- errors=['目标未明确：需要目标实体或清楚的场景目标。', '距离未明确：需要至少给出贴身/近距/标准/远距或步数。', '弹药未明确：射击前必须选择弹药。', '武器未明确：保存前必须指定武器，不能由引擎默认选择。']
- warnings=[]
- 

### ISSUE · natural consumption variants · shoot burst bolt

- Observed: start=action:combat can_proceed=False preview=combat:clarify ready=False before=20.0 after=20.0 committed=False ok=False
- Expected: natural command should decrement item:burst-thorn-bolts 20->19 or block clearly before save
- Issue: `natural_consumption_not_ready`
- player_message=还需要补充 target, weapon, ammo, distance，我才能可靠结算这次 combat。
- errors=['目标未明确：需要目标实体或清楚的场景目标。', '距离未明确：需要至少给出贴身/近距/标准/远距或步数。', '弹药未明确：射击前必须选择弹药。', '武器未明确：保存前必须指定武器，不能由引擎默认选择。']
- warnings=[]
- 

### ISSUE · natural consumption variants · shoot toxic thorn bolt

- Observed: start=action:combat can_proceed=False preview=combat:clarify ready=False before=20.0 after=20.0 committed=False ok=False
- Expected: natural command should decrement item:toxic-thorn-bolts 20->19 or block clearly before save
- Issue: `natural_consumption_not_ready`
- player_message=还需要补充 target, weapon, ammo, distance，我才能可靠结算这次 combat。
- errors=['目标未明确：需要目标实体或清楚的场景目标。', '距离未明确：需要至少给出贴身/近距/标准/远距或步数。', '弹药未明确：射击前必须选择弹药。', '武器未明确：保存前必须指定武器，不能由引擎默认选择。']
- warnings=[]
- 

### ISSUE · natural consumption variants · disassemble landmine

- Observed: start=query:entity can_proceed=True preview=query:ready ready=False before=1.0 after=1.0 committed=False ok=False
- Expected: natural command should decrement item:landmine-m2 1->0 or block clearly before save
- Issue: `natural_consumption_misread_as_query`
- player_message=这是只读查询请求，不需要行动预演或保存。
- errors=[]
- warnings=[]
- 

### ISSUE · natural consumption variants · feed with berries

- Observed: start=action:routine can_proceed=True preview=routine:ready ready=True before=0.5 after=0.5 committed=True ok=True
- Expected: natural command should decrement item:v1-8182ae0835 0.5->0.25 or block clearly before save
- Issue: `natural_consumption_committed_without_decrement`
- player_message=已识别为日常维护。这是低风险 routine，不会自动制造资源、推进关系或创建新事实。
- errors=[]
- warnings=[]
- 

### ISSUE · natural consumption variants · season meal with salt

- Observed: start=query:entity can_proceed=True preview=query:ready ready=False before=0.5 after=0.5 committed=False ok=False
- Expected: natural command should decrement item:salt 0.5->0.4 or block clearly before save
- Issue: `natural_consumption_misread_as_query`
- player_message=这是只读查询请求，不需要行动预演或保存。
- errors=[]
- warnings=[]
- 

### ISSUE · natural consumption variants · drink all water

- Observed: start=query:entity can_proceed=True preview=query:ready ready=False before=4.0 after=4.0 committed=False ok=False
- Expected: natural command should decrement item:v1-0b81d0d73c 4->0 or block clearly before save
- Issue: `natural_consumption_misread_as_query`
- player_message=这是只读查询请求，不需要行动预演或保存。
- errors=[]
- warnings=[]
- 

### PASS · manual consumption · consume one water spinach

- Observed: before=13.0 after=12.0 committed=True ok=True health=True
- Expected: quantity becomes 12, commit ok, health ok

### PASS · manual consumption · consume fractional salt

- Observed: before=0.5 after=0.25 committed=True ok=True health=True
- Expected: quantity becomes 0.25, commit ok, health ok

### PASS · manual consumption · drink half liter water

- Observed: before=4.0 after=3.5 committed=True ok=True health=True
- Expected: quantity becomes 3.5, commit ok, health ok

### PASS · manual consumption · use pine nut oil

- Observed: before=3.0 after=2.5 committed=True ok=True health=True
- Expected: quantity becomes 2.5, commit ok, health ok

### PASS · manual consumption · use black powder

- Observed: before=0.5 after=0.25 committed=True ok=True health=True
- Expected: quantity becomes 0.25, commit ok, health ok

### PASS · manual consumption · use hemp fiber

- Observed: before=3.0 after=2.5 committed=True ok=True health=True
- Expected: quantity becomes 2.5, commit ok, health ok

### PASS · manual consumption · use milky residue

- Observed: before=40.0 after=30.0 committed=True ok=True health=True
- Expected: quantity becomes 30, commit ok, health ok

### PASS · manual consumption · consume single purple leaf

- Observed: before=1.0 after=0.0 committed=True ok=True health=True
- Expected: quantity becomes 0, commit ok, health ok

### PASS · manual consumption · consume all plain bolts

- Observed: before=3.0 after=0.0 committed=True ok=True health=True
- Expected: quantity becomes 0, commit ok, health ok

### PASS · manual consumption · manual ammo decrement

- Observed: before=12.0 after=11.0 committed=True ok=True health=True
- Expected: quantity becomes 11, commit ok, health ok
- state_audit=HIGH_RISK_ITEM_METADATA_INCOMPLETE

### PASS · manual consumption extended · manual lettuce leaf

- Observed: before=3.0 after=2.0 committed=True ok=True health=True query_ok=True
- Expected: quantity becomes 2, query updates immediately, health ok
- query=## 装备/物品：红叶生菜

| 字段 | 值 |
|------|----|
| ID | `item:v1-f07d297448` |
| 类型 | 物品 |
| 分类 | 食物 |
| 位置 | loc:home-mycelium-house |
| 状态 | 活跃 |
| 数量 | 2片 |
| 品质 | 未知 |
| 装备槽 | 无 |

### 摘要
蔬菜

### 备注
- last_consumption_probe: 

### PASS · manual consumption extended · manual amaranth leaves

- Observed: before=8.0 after=6.0 committed=True ok=True health=True query_ok=True
- Expected: quantity becomes 6, query updates immediately, health ok
- query=## 装备/物品：苋菜大叶

| 字段 | 值 |
|------|----|
| ID | `item:v1-e267e90894` |
| 类型 | 物品 |
| 分类 | 食物 |
| 位置 | loc:home-mycelium-house |
| 状态 | 活跃 |
| 数量 | 6片 |
| 品质 | 未知 |
| 装备槽 | 无 |

### 摘要
蔬菜

### 备注
- last_consumption_probe: 

### PASS · manual consumption extended · manual wild onion

- Observed: before=3.0 after=2.0 committed=True ok=True health=True query_ok=True
- Expected: quantity becomes 2, query updates immediately, health ok
- query=## 装备/物品：野葱

| 字段 | 值 |
|------|----|
| ID | `item:v1-0629e81966` |
| 类型 | 物品 |
| 分类 | 食物 |
| 位置 | loc:home-mycelium-house |
| 状态 | 活跃 |
| 数量 | 2根 |
| 品质 | 未知 |
| 装备槽 | 无 |

### 摘要
调料

### 备注
- last_consumption_probe: te

### PASS · manual consumption extended · manual garlic leaf

- Observed: before=2.0 after=1.0 committed=True ok=True health=True query_ok=True
- Expected: quantity becomes 1, query updates immediately, health ok
- query=## 装备/物品：蒜叶

| 字段 | 值 |
|------|----|
| ID | `item:v1-8aa915dbc4` |
| 类型 | 物品 |
| 分类 | 食物 |
| 位置 | loc:home-mycelium-house |
| 状态 | 活跃 |
| 数量 | 1片 |
| 品质 | 未知 |
| 装备槽 | 无 |

### 摘要
调料

### 备注
- last_consumption_probe: te

### PASS · manual consumption extended · manual red chili

- Observed: before=1.0 after=0.0 committed=True ok=True health=True query_ok=True
- Expected: quantity becomes 0, query updates immediately, health ok
- query=## 装备/物品：红辣椒

| 字段 | 值 |
|------|----|
| ID | `item:v1-d409c6757a` |
| 类型 | 物品 |
| 分类 | 食物 |
| 位置 | loc:home-mycelium-house |
| 状态 | 活跃 |
| 数量 | 0颗 |
| 品质 | 未知 |
| 装备槽 | 无 |

### 摘要
调料

### 备注
- last_consumption_probe: t

### PASS · manual consumption extended · manual red berries

- Observed: before=0.5 after=0.25 committed=True ok=True health=True query_ok=True
- Expected: quantity becomes 0.25, query updates immediately, health ok
- query=## 装备/物品：红浆果

| 字段 | 值 |
|------|----|
| ID | `item:v1-8182ae0835` |
| 类型 | 物品 |
| 分类 | 食物 |
| 位置 | loc:home-mycelium-house |
| 状态 | 活跃 |
| 数量 | 0.25竹杯 |
| 品质 | 未知 |
| 装备槽 | 无 |

### 摘要
红浆果，约半竹杯；可食用或继续用于调味/发酵，存于新屋厨房角。

#

### PASS · manual consumption extended · manual pine nuts

- Observed: before=1.0 after=0.5 committed=True ok=True health=True query_ok=True
- Expected: quantity becomes 0.5, query updates immediately, health ok
- query=## 装备/物品：松子仁

| 字段 | 值 |
|------|----|
| ID | `item:v1-b4fc16271b` |
| 类型 | 物品 |
| 分类 | 食物 |
| 位置 | loc:home-mycelium-house |
| 状态 | 活跃 |
| 数量 | 0.5份 |
| 品质 | 未知 |
| 装备槽 | 无 |

### 摘要
松子仁，约一碗；当前按1份储粮登记，存六边形菌丝复合屋厨房角或储物墙。


### PASS · manual consumption extended · manual ordinary resin

- Observed: before=0.5 after=0.25 committed=True ok=True health=True query_ok=True
- Expected: quantity becomes 0.25, query updates immediately, health ok
- query=## 装备/物品：普通残胶（S4）

| 字段 | 值 |
|------|----|
| ID | `item:v1-9bb88c5944` |
| 类型 | 物品 |
| 分类 | 材料 |
| 位置 | loc:home-mycelium-house |
| 状态 | 活跃 |
| 数量 | 0.25竹杯 |
| 品质 | 未知 |
| 装备槽 | 无 |

### 摘要
普通残胶（S4），约半竹杯；防水/透明涂层材料。

###

### PASS · manual consumption extended · manual hardened resin

- Observed: before=80.0 after=70.0 committed=True ok=True health=True query_ok=True
- Expected: quantity becomes 70, query updates immediately, health ok
- query=## 装备/物品：硬化残胶

| 字段 | 值 |
|------|----|
| ID | `item:v1-0322977645` |
| 类型 | 物品 |
| 分类 | 材料 |
| 位置 | loc:home-mycelium-house |
| 状态 | 活跃 |
| 数量 | 70ml |
| 品质 | 未知 |
| 装备槽 | 无 |

### 摘要
硬化残胶，约80ml；可作为浓胶、硬化涂料或防水修补材料，存于新屋储物

### PASS · manual consumption extended · manual acid resin

- Observed: before=30.0 after=25.0 committed=True ok=True health=True query_ok=True
- Expected: quantity becomes 25, query updates immediately, health ok
- query=## 装备/物品：酸残胶（S1）

| 字段 | 值 |
|------|----|
| ID | `item:v1-18a38459f1` |
| 类型 | 物品 |
| 分类 | 材料 |
| 位置 | loc:home-mycelium-house |
| 状态 | 活跃 |
| 数量 | 25ml |
| 品质 | 未知 |
| 装备槽 | 无 |

### 摘要
酸残胶（S1），约30ml；已按低风险材料封入竹杯，当前存新屋储

### PASS · manual consumption extended · manual sulfur shards

- Observed: before=1.0 after=0.5 committed=True ok=True health=True query_ok=True
- Expected: quantity becomes 0.5, query updates immediately, health ok
- query=## 装备/物品：硫磺碎晶

| 字段 | 值 |
|------|----|
| ID | `item:v1-4681d8edfb` |
| 类型 | 物品 |
| 分类 | 材料 |
| 位置 | loc:home-old-hut |
| 状态 | 活跃 |
| 数量 | 0.5把 |
| 品质 | 未知 |
| 装备槽 | 无 |

### 摘要
约一把淡鹅黄色硫磺碎晶，部分已用；来自L7溪源泉眼采集，当前随火药材料存旧小屋材料仓

### PASS · manual consumption extended · manual niter needles

- Observed: before=0.5 after=0.25 committed=True ok=True health=True query_ok=True
- Expected: quantity becomes 0.25, query updates immediately, health ok
- query=## 装备/物品：硝石针晶

| 字段 | 值 |
|------|----|
| ID | `item:v1-26667819cb` |
| 类型 | 物品 |
| 分类 | 材料 |
| 位置 | loc:home-old-hut |
| 状态 | 活跃 |
| 数量 | 0.25杯 |
| 品质 | 未知 |
| 装备槽 | 无 |

### 摘要
约小半杯火药原料，大部分已碾粉；来自L12砂岩岩壳采集，当前随火药材料存旧小屋材料

### PASS · manual consumption extended · manual tung oil

- Observed: before=1.0 after=0.75 committed=True ok=True health=True query_ok=True
- Expected: quantity becomes 0.75, query updates immediately, health ok
- query=## 装备/物品：生桐油

| 字段 | 值 |
|------|----|
| ID | `item:v1-e247bca14a` |
| 类型 | 物品 |
| 分类 | 材料 |
| 位置 | loc:home-old-hut |
| 状态 | 活跃 |
| 数量 | 0.75L |
| 品质 | 未知 |
| 装备槽 | 无 |

### 摘要
防水涂层

### 备注
- last_consumption_probe: tem

### PASS · manual consumption extended · manual spare rope

- Observed: before=3.0 after=2.5 committed=True ok=True health=True query_ok=True
- Expected: quantity becomes 2.5, query updates immediately, health ok
- query=## 装备/物品：备用纤维绳

| 字段 | 值 |
|------|----|
| ID | `item:v1-515c3e4a2f` |
| 类型 | 物品 |
| 分类 | 材料 |
| 位置 | loc:home-old-hut |
| 状态 | 活跃 |
| 数量 | 2.5m |
| 品质 | 未知 |
| 装备槽 | 无 |

### 摘要
备用纤维绳，约3m；当前归入旧小屋绳索/工具材料区，可用于捆扎、修补或临时固定。


### PASS · manual consumption extended · manual lake fiber

- Observed: before=1.0 after=0.5 committed=True ok=True health=True query_ok=True
- Expected: quantity becomes 0.5, query updates immediately, health ok
- query=## 装备/物品：湖边细纤维

| 字段 | 值 |
|------|----|
| ID | `item:v1-ac25ff32a4` |
| 类型 | 物品 |
| 分类 | 材料 |
| 位置 | loc:l01-creek |
| 状态 | 活跃 |
| 数量 | 0.5束 |
| 品质 | 未知 |
| 装备槽 | 无 |

### 摘要
湖边细纤维样本，1束；极细、极滑、极韧，可能是动物筋类材料，当前位置记录需下次盘点确认。

### PASS · manual consumption extended · manual old poison bolt

- Observed: before=9.0 after=8.0 committed=True ok=True health=True query_ok=True
- Expected: quantity becomes 8, query updates immediately, health ok
- query=## 装备/物品：旧毒弩箭

| 字段 | 值 |
|------|----|
| ID | `item:poison-bolts` |
| 类型 | 物品 |
| 分类 | 弹药 |
| 位置 | loc:home-clearing |
| 状态 | 已退役 |
| 数量 | 8支 |
| 品质 | 未知 |
| 装备槽 | 无 |

### 摘要
旧毒弩箭，结构化库存记录为9支；毒剂来源已确认为见血封喉树，有效期不明确，当前可用性需

### PASS · manual consumption extended · manual bamboo arrows

- Observed: before=15.0 after=10.0 committed=True ok=True health=True query_ok=True
- Expected: quantity becomes 10, query updates immediately, health ok
- query=## 装备/物品：竹箭（弓用）

| 字段 | 值 |
|------|----|
| ID | `item:v1-9a74235657` |
| 类型 | 物品 |
| 分类 | 弹药 |
| 位置 | loc:home-clearing |
| 状态 | 已退役 |
| 数量 | 10支 |
| 品质 | 未知 |
| 装备槽 | 无 |

### 摘要
退役

### 备注
- last_consumption_probe: te

### PASS · manual consumption extended · manual frost bolt

- Observed: before=20.0 after=19.0 committed=True ok=True health=True query_ok=True
- Expected: quantity becomes 19, query updates immediately, health ok
- state_audit=HIGH_RISK_ITEM_METADATA_INCOMPLETE
- query=## 装备/物品：霜白冻箭

| 字段 | 值 |
|------|----|
| ID | `item:frost-thorn-bolts` |
| 类型 | 物品 |
| 分类 | 弹药 |
| 位置 | pc:shenyan |
| 状态 | 活跃 |
| 数量 | 19支 |
| 品质 | 未知 |
| 装备槽 | 无 |

### 摘要
霜寒控场箭；拳大范围冻伤，适合减速、冻结湿表面和压制冷血目标。

### 弹药档案
| 字

### PASS · manual consumption extended · manual burst bolt

- Observed: before=20.0 after=19.0 committed=True ok=True health=True query_ok=True
- Expected: quantity becomes 19, query updates immediately, health ok
- state_audit=HIGH_RISK_ITEM_METADATA_INCOMPLETE
- query=## 装备/物品：赤红炸箭

| 字段 | 值 |
|------|----|
| ID | `item:burst-thorn-bolts` |
| 类型 | 物品 |
| 分类 | 弹药 |
| 位置 | pc:shenyan |
| 状态 | 活跃 |
| 数量 | 19支 |
| 品质 | 未知 |
| 装备槽 | 无 |

### 摘要
撞击爆裂箭；拳大空腔爆裂，适合冲击、破甲和驱散。

### 弹药档案
| 字段 | 值 |

### PASS · manual consumption extended · manual toxic bolt

- Observed: before=20.0 after=19.0 committed=True ok=True health=True query_ok=True
- Expected: quantity becomes 19, query updates immediately, health ok
- state_audit=HIGH_RISK_ITEM_METADATA_INCOMPLETE
- query=## 装备/物品：紫黑毒箭

| 字段 | 值 |
|------|----|
| ID | `item:toxic-thorn-bolts` |
| 类型 | 物品 |
| 分类 | 弹药 |
| 位置 | pc:shenyan |
| 状态 | 活跃 |
| 数量 | 19支 |
| 品质 | 未知 |
| 装备槽 | 无 |

### 摘要
神经+血液双毒箭；强于见血封喉，适合快速削弱或击杀活体。

### 弹药档案
| 字段 |

### PASS · manual consumption extended · manual plain bolt partial

- Observed: before=3.0 after=2.0 committed=True ok=True health=True query_ok=True
- Expected: quantity becomes 2, query updates immediately, health ok
- query=## 装备/物品：旧普通箭

| 字段 | 值 |
|------|----|
| ID | `item:plain-bolts` |
| 类型 | 物品 |
| 分类 | 弹药 |
| 位置 | loc:home-clearing |
| 状态 | 已退役 |
| 数量 | 2支 |
| 品质 | 未知 |
| 装备槽 | 无 |

### 摘要
无

### 备注
- last_consumption_probe: temporar

### PASS · manual consumption extended · manual landmine removed

- Observed: before=1.0 after=0.0 committed=True ok=True health=True query_ok=True
- Expected: quantity becomes 0, query updates immediately, health ok
- query=## 装备/物品：M2 围栏竹门外地雷

| 字段 | 值 |
|------|----|
| ID | `item:landmine-m2` |
| 类型 | 物品 |
| 分类 | 陷阱 |
| 位置 | loc:home-clearing |
| 状态 | 活跃 |
| 数量 | 0枚 |
| 品质 | 未知 |
| 装备槽 | 无 |

### 摘要
埋在围栏竹门外侧，东西绊线，使用造粒火药和弹片，属于基地外围被动防御陷阱。



### PASS · manual consumption extended · manual bamboo water all

- Observed: before=4.0 after=0.0 committed=True ok=True health=True query_ok=True
- Expected: quantity becomes 0, query updates immediately, health ok
- query=## 装备/物品：竹水筒

| 字段 | 值 |
|------|----|
| ID | `item:v1-0b81d0d73c` |
| 类型 | 物品 |
| 分类 | 工具 |
| 位置 | loc:home-mycelium-house |
| 状态 | 活跃 |
| 数量 | 0L |
| 品质 | 满 |
| 装备槽 | 无 |

### 摘要
约4L竹水筒；第28天上午在L1小溪装满溪水后带回六边形菌丝复合屋。

###

### PASS · manual consumption extended · manual berry vinegar

- Observed: before=1.0 after=0.5 committed=True ok=True health=True query_ok=True
- Expected: quantity becomes 0.5, query updates immediately, health ok
- query=## 装备/物品：浆果醋

| 字段 | 值 |
|------|----|
| ID | `item:berry-vinegar` |
| 类型 | 物品 |
| 分类 | 食物 |
| 位置 | loc:home-mycelium-d-warehouse |
| 状态 | 活跃 |
| 数量 | 0.5竹杯 |
| 品质 | 已开封成熟 |
| 装备槽 | 无 |

### 摘要
第9天启动、第23天成熟、第25天已开封验证的成熟浆

### PASS · manual consumption extended · manual sulfur sample

- Observed: before=1.0 after=0.0 committed=True ok=True health=True query_ok=True
- Expected: quantity becomes 0, query updates immediately, health ok
- query=## 装备/物品：硫磺样本

| 字段 | 值 |
|------|----|
| ID | `item:v1-d88d8320cf` |
| 类型 | 物品 |
| 分类 | 材料 |
| 位置 | loc:home-old-hut |
| 状态 | 活跃 |
| 数量 | 0份 |
| 品质 | 未知 |
| 装备槽 | 无 |

### 摘要
硫磺样本，1份L7泉眼采集参考样本；当前存旧小屋材料仓库，用于辨识硫磺资源和火药配比参考

### ISSUE · guardrail · narrated consumption without upsert

- Observed: before=13.0 after=13.0 committed=True ok=True
- Expected: should block or remain uncommitted when consumption is not structured
- Issue: `narrated_consumption_committed_without_decrement`
- state_audit=MATERIAL_CONSUMPTION_NOT_STRUCTURED; STRUCTURED_STATE_REQUIRED; NARRATED_CONSUMPTION_WITHOUT_STATE_OP

### ISSUE · guardrail · event says consumed but upsert keeps same quantity

- Observed: before=13.0 after=13.0 committed=True ok=True
- Expected: should block inconsistent consumption/no-op quantity
- Issue: `consumption_noop_quantity_committed`

### ISSUE · guardrail · overconsume into negative quantity

- Observed: before=0.5 after=-0.5 committed=True ok=False
- Expected: negative inventory should be blocked before write and leave quantity unchanged
- Issue: `negative_quantity_written_or_reported_late`
- check_errors=item:salt 盐 has negative quantity -0.5

### ISSUE · guardrail · unit mismatch on decrement

- Observed: before=0.5 after=0.25支 committed=True ok=True
- Expected: unit changes during pure consumption should be blocked
- Issue: `unit_mismatch_committed`

### ISSUE · guardrail · minimal quantity upsert preserves metadata

- Observed: before_qty=5.0 after_qty=4.0 owner=pc:shenyan->None location=None->None properties_preserved=False committed=True ok=True
- Expected: quantity decrements while owner/location/properties remain intact
- Issue: `minimal_upsert_loses_metadata`
- state_audit=HIGH_RISK_ITEM_METADATA_INCOMPLETE

### PASS · guardrail extended · non-numeric quantity on decrement

- Observed: committed=False ok=False unchanged=True
- Expected: should block non-numeric quantity before write
- error=ValueError: Invalid turn delta:
- delta: $.upsert_entities[0].item.quantity: must be number
- $.upsert_entities[0].item.quantity: must be number

### ISSUE · guardrail extended · null quantity on exact decrement

- Observed: committed=True ok=True unchanged=False
- Expected: should block null quantity when exact stock is decremented
- Issue: `null_quantity_committed`
- state_audit=HIGH_RISK_ITEM_METADATA_INCOMPLETE

### ISSUE · guardrail extended · missing unit on decrement

- Observed: committed=True ok=True unchanged=False
- Expected: should block losing unit during pure consumption
- Issue: `missing_unit_committed`
- state_audit=HIGH_RISK_ITEM_METADATA_INCOMPLETE

### ISSUE · guardrail extended · event consumes salt but upsert decrements water

- Observed: committed=True ok=True unchanged=False
- Expected: should block event/upsert item mismatch
- Issue: `consumed_item_upsert_mismatch_committed`

### ISSUE · guardrail extended · payload after quantity mismatches upsert

- Observed: committed=True ok=True unchanged=False
- Expected: should block payload after_quantity that disagrees with upsert quantity
- Issue: `payload_after_quantity_mismatch_committed`

### ISSUE · guardrail extended · payload before quantity mismatches db

- Observed: committed=True ok=True unchanged=False
- Expected: should block payload before_quantity that disagrees with current stock
- Issue: `payload_before_quantity_mismatch_committed`

### ISSUE · guardrail extended · payload consumed quantity too high

- Observed: committed=True ok=True unchanged=False
- Expected: should block consumed_quantity inconsistent with before/after
- Issue: `payload_consumed_quantity_mismatch_committed`

### ISSUE · guardrail extended · negative consumed quantity payload

- Observed: committed=True ok=True unchanged=False
- Expected: should block negative consumed_quantity in event payload
- Issue: `negative_consumed_quantity_committed`

### ISSUE · guardrail extended · payload consumed item id mismatch

- Observed: committed=True ok=True unchanged=False
- Expected: should block consumed_item_id that disagrees with upsert entity
- Issue: `payload_consumed_item_mismatch_committed`

### ISSUE · guardrail extended · category changed during decrement

- Observed: committed=True ok=True unchanged=False
- Expected: should block category mutation during pure consumption
- Issue: `category_mutation_committed`

### ISSUE · guardrail extended · quality changed during decrement

- Observed: committed=True ok=True unchanged=False
- Expected: should block quality mutation during pure consumption
- Issue: `quality_mutation_committed`

### ISSUE · guardrail extended · name changed during decrement

- Observed: committed=True ok=True unchanged=False
- Expected: should block renaming item during pure consumption
- Issue: `name_mutation_committed`

### ISSUE · guardrail extended · status archived during decrement

- Observed: committed=True ok=True unchanged=False
- Expected: should block status mutation during pure consumption
- Issue: `status_mutation_committed`

### ISSUE · guardrail extended · visibility hidden during decrement

- Observed: committed=True ok=True unchanged=False
- Expected: should block visibility mutation during pure consumption
- Issue: `visibility_mutation_committed`

### ISSUE · guardrail extended · location and owner lost during decrement

- Observed: committed=True ok=True unchanged=False
- Expected: should block dropping storage location/owner during pure consumption
- Issue: `storage_location_lost_committed`
- state_audit=HIGH_RISK_ITEM_METADATA_INCOMPLETE

### ISSUE · guardrail extended · properties lost during decrement

- Observed: committed=True ok=True unchanged=False
- Expected: should block losing high-risk item properties during pure consumption
- Issue: `properties_lost_committed`
- state_audit=HIGH_RISK_ITEM_METADATA_INCOMPLETE

### ISSUE · guardrail extended · stackable changed during decrement

- Observed: committed=True ok=True unchanged=False
- Expected: should block stackable mutation during pure consumption
- Issue: `stackable_mutation_committed`

### ISSUE · guardrail extended · durability changed during decrement

- Observed: committed=True ok=True unchanged=False
- Expected: should block durability mutation during pure consumption
- Issue: `durability_mutation_committed`

### ISSUE · guardrail extended · equipped slot changed during decrement

- Observed: committed=True ok=True unchanged=False
- Expected: should block equipped_slot mutation during pure consumption
- Issue: `equipped_slot_mutation_committed`

### ISSUE · guardrail extended · minimal toxic bolt upsert loses metadata

- Observed: committed=True ok=True unchanged=False
- Expected: should preserve owner/location/properties when decrementing high-risk ammo
- Issue: `minimal_high_risk_upsert_loses_metadata`
- state_audit=HIGH_RISK_ITEM_METADATA_INCOMPLETE

### ISSUE · stale write · stale consumption without expected_turn_id

- Observed: initial_turn=turn:000044 after=0.4 first_ok=True stale_committed=True stale_ok=True
- Expected: stale second consumption should not overwrite a fresher quantity
- Issue: `stale_consumption_overwrites_quantity`

### PASS · stale write · stale consumption with expected_turn_id

- Observed: initial_turn=turn:000044 after=0.25 first_ok=True stale_committed=False error=ValueError: stale write: expected current turn turn:000044, actual turn:000045
- Expected: expected_turn_id should block stale write and preserve 0.25
- error=ValueError: stale write: expected current turn turn:000044, actual turn:000045
