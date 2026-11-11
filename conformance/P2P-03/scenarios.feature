# Generated from workflows/procure-to-pay/P2P-03/workflow.yaml by tooling/workflow_render.py. Do not edit.
# Happy path = the shortest start-to-end path (governance/workflow-rules.yaml, conformance C2).
@P2P-03 @v1.0.0
Feature: P2P-03 Invoice approval

  @happy @path-1
  Scenario: Path 1
    Given the process "P2P-03" starts with "Goods delivered" [11:241]
    When "Supplier (external)" performs "Send invoice" [11:244]
    Then the process ends with "Invoice sent" [11:246]

  @path-2
  Scenario: Path 2 (No)
    Given the process "P2P-03" starts with "Goods delivered" [11:241]
    When "Supplier (external)" performs "Send invoice" [11:244]
    And "AP Clerk" performs "Register invoice" [11:249]
    And "AP Clerk" performs "Match to purchase order" [11:251]
    And "AP Clerk" decides "PO matches?" [11:256]
    And the decision resolves to "No"
    And "AP Clerk" performs "Return invoice to supplier" [11:267]
    Then the process ends with "Invoice rejected" [11:269]

  @path-3
  Scenario: Path 3 (Yes, No)
    Given the process "P2P-03" starts with "Goods delivered" [11:241]
    When "Supplier (external)" performs "Send invoice" [11:244]
    And "AP Clerk" performs "Register invoice" [11:249]
    And "AP Clerk" performs "Match to purchase order" [11:251]
    And "AP Clerk" decides "PO matches?" [11:256]
    And the decision resolves to "Yes"
    And "AP Clerk" decides "Amount > €5,000?" [11:259]
    And the decision resolves to "No"
    And "AP Clerk" performs "Schedule payment" [11:262]
    Then the process ends with "Invoice paid" [11:264]

  @path-4
  Scenario: Path 4 (Yes, Yes)
    Given the process "P2P-03" starts with "Goods delivered" [11:241]
    When "Supplier (external)" performs "Send invoice" [11:244]
    And "AP Clerk" performs "Register invoice" [11:249]
    And "AP Clerk" performs "Match to purchase order" [11:251]
    And "AP Clerk" decides "PO matches?" [11:256]
    And the decision resolves to "Yes"
    And "AP Clerk" decides "Amount > €5,000?" [11:259]
    And the decision resolves to "Yes"
    And "Finance Manager" performs "Approve invoice" [11:280]
    And "AP Clerk" performs "Schedule payment" [11:262]
    Then the process ends with "Invoice paid" [11:264]
