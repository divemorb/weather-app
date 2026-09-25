---
alwaysApply: true
---

In this environment, `create_new_file` and `edit_existing_file` have repeatedly truncated files mid-write (ending mid-line or mid-statement). After EVERY file create/edit, verify completeness before moving on: check `wc -l`, view the tail, and for Python run `python -m py_compile` (or `ast.parse`). If truncated, delete the file (`rm`) and recreate it with `create_new_file` (fresh creates have been reliable), then re-verify.