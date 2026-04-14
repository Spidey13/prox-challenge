"""Quick smoke test for _strip_code_fences."""
import os, sys, logging
logging.disable(logging.CRITICAL)
os.environ["ANTHROPIC_API_KEY"] = "test"

from agent import _strip_code_fences

# Test 1: Normal triple-backtick fence
test1 = "```html\n<!DOCTYPE html><html><body><h1>Hello</h1></body></html>\n```"
r1 = _strip_code_fences(test1)
assert r1.startswith("<!DOCTYPE"), f"Test 1 failed: {r1[:60]}"
assert "```" not in r1, "Test 1: fences not stripped"
print("Test 1 PASSED: normal code fences stripped")

# Test 2: Plain HTML (no fences)
test2 = "<!DOCTYPE html><html><body></body></html>"
r2 = _strip_code_fences(test2)
assert r2 == test2, "Test 2: plain HTML should be unchanged"
print("Test 2 PASSED: plain HTML unchanged")

# Test 3: Opening fence only (no closing)
test3 = "```html\n<!DOCTYPE html><html><body>test</body></html>"
r3 = _strip_code_fences(test3)
assert r3.startswith("<!DOCTYPE"), f"Test 3 failed: {r3[:60]}"
print("Test 3 PASSED: opening-only fence stripped")

# Test 4: Fence with whitespace before closing
test4 = "```html\n<!DOCTYPE html><html><body>x</body></html>\n```  \n"
r4 = _strip_code_fences(test4)
assert r4.startswith("<!DOCTYPE"), f"Test 4 failed: {r4[:60]}"
assert "```" not in r4, "Test 4: fences not stripped"
print("Test 4 PASSED: trailing whitespace handled")

# Test 5: Fence with just ``` (no language tag)
test5 = "```\n<!DOCTYPE html><html><body>z</body></html>\n```"
r5 = _strip_code_fences(test5)
assert r5.startswith("<!DOCTYPE"), f"Test 5 failed: {r5[:60]}"
print("Test 5 PASSED: fence without language tag stripped")

print()
print("ALL FENCE STRIP TESTS PASSED")
