# revenant-dev backend API

Plain Python functions in `src/revenant_dev/api.py`. There is no web server. Each function takes a
`TraceStore` (the SQLite store from revenant-core) and returns JSON-compatible data. Every return
value round-trips through `canonical_json`.

| Function | Arguments | Returns |
|---|---|---|
| `list_sessions` | `store` | list of session summaries |
| `get_session` | `store, session_id` | one session with every stored event |
| `replay_summary` | `store, session_id, *, workspace_root` | replay counters and the replayed answer |
| `find_bad_edit` | `store, session_id` | the first bad edit, or `null` |
| `fork` | `store, parent_session_id, at_step, *, override=None, use_override=False` | child id and diff |

`workspace_root` is the folder that holds one workspace per session. Replay never writes there.

## `list_sessions(store)`

```json
[
  {
    "session_id": "47a2b7a2e1cd452fadf5a9309112ccd5",
    "created_at": "2026-11-25T16:31:44.675462+00:00",
    "parent_session_id": null,
    "parent_step": null,
    "event_count": 24,
    "task": "Fix sample_pkg.stats.mean so that the test suite passes."
  },
  {
    "session_id": "738c415e85ec451c85940a6cb4dc9594",
    "created_at": "2026-11-25T16:31:59.058754+00:00",
    "parent_session_id": null,
    "parent_step": null,
    "event_count": 28,
    "task": "Fix sample_pkg.stats.mean so that the test suite passes."
  }
]
```

One entry per session, oldest first. `task` is `null` for a session without metadata. The
`event_count` is the number of stored events.

## `get_session(store, session_id)`

```json
{
  "session_id": "47a2b7a2e1cd452fadf5a9309112ccd5",
  "created_at": "2026-11-25T16:31:44.675462+00:00",
  "parent_session_id": null,
  "parent_step": null,
  "metadata": {
    "extra_reads": 0,
    "max_steps": 12,
    "task": "Fix sample_pkg.stats.mean so that the test suite passes."
  },
  "events": [
    {
      "event_id": "1324f7f6a31c4773b3c1f94de90a623e",
      "session_id": "47a2b7a2e1cd452fadf5a9309112ccd5",
      "step": 0,
      "type": "session_start",
      "payload": {
        "metadata": {
          "extra_reads": 0,
          "max_steps": 12,
          "task": "Fix sample_pkg.stats.mean so that the test suite passes."
        }
      },
      "timestamp": "2026-11-25T16:31:44.772421+00:00",
      "parent_step": null,
      "prev_hash": "0000000000000000000000000000000000000000000000000000000000000000",
      "hash": "55e4e5b7b317d5a6539eb0da08ac79abbf6becf5cd53df4a165cc35e62a7caf9"
    },
    {
      "event_id": "86a177f52699411796d1bddba02628b8",
      "session_id": "47a2b7a2e1cd452fadf5a9309112ccd5",
      "step": 1,
      "type": "llm_call",
      "payload": {
        "args": {
          "messages": [
            {
              "content": "Fix sample_pkg.stats.mean so that the test suite passes.",
              "role": "user"
            }
          ],
          "turn": 0
        },
        "fingerprint": "29b045e812f8af786cb01483b1572b01a0e52f8e2c99f9a4160b7b7699257574",
        "name": "llm"
      },
      "timestamp": "2026-11-25T16:31:45.094220+00:00",
      "parent_step": null,
      "prev_hash": "55e4e5b7b317d5a6539eb0da08ac79abbf6becf5cd53df4a165cc35e62a7caf9",
      "hash": "7a96de6c1b335abde3fd13be1259d2cc8156115f21019343784b98a471bbb48e"
    },
    {
      "event_id": "9028edbba8ce45128fa5b5f83679bdd4",
      "session_id": "47a2b7a2e1cd452fadf5a9309112ccd5",
      "step": 2,
      "type": "tool_result",
      "payload": {
        "name": "llm",
        "result": {
          "args": {
            "path": "sample_pkg/stats.py"
          },
          "tool": "read_file"
        }
      },
      "timestamp": "2026-11-25T16:31:45.152191+00:00",
      "parent_step": 1,
      "prev_hash": "7a96de6c1b335abde3fd13be1259d2cc8156115f21019343784b98a471bbb48e",
      "hash": "dae804f7505bb148887b59e66f07624321e114da12f313bdcc40285abfdd6c8d"
    },
    {
      "event_id": "83b77ac5d8364d19b4df147ba5164545",
      "session_id": "47a2b7a2e1cd452fadf5a9309112ccd5",
      "step": 3,
      "type": "tool_call",
      "payload": {
        "args": {
          "path": "sample_pkg/stats.py"
        },
        "fingerprint": "ac257590f58cac523258a677109f61cfe4d53664a1021fee0e05c89b8c6807fb",
        "name": "read_file"
      },
      "timestamp": "2026-11-25T16:31:45.225146+00:00",
      "parent_step": null,
      "prev_hash": "dae804f7505bb148887b59e66f07624321e114da12f313bdcc40285abfdd6c8d",
      "hash": "99640bc4431f0dafc3a1d03e8cfce22ed57cde0d8489bf3c10c75d23e083f9bf"
    },
    {
      "event_id": "9d4097f6ae574791acea95d4e7f18a7f",
      "session_id": "47a2b7a2e1cd452fadf5a9309112ccd5",
      "step": 4,
      "type": "tool_result",
      "payload": {
        "name": "read_file",
        "result": {
          "content": "\"\"\"Statistics helpers.\"\"\"\n\n\ndef mean(values: list[float]) -> float:\n    \"\"\"Return the arithmetic mean of values.\"\"\"\n    return sum(values) / (len(values) - 1)\n",
          "path": "sample_pkg/stats.py"
        }
      },
      "timestamp": "2026-11-25T16:31:45.294106+00:00",
      "parent_step": 3,
      "prev_hash": "99640bc4431f0dafc3a1d03e8cfce22ed57cde0d8489bf3c10c75d23e083f9bf",
      "hash": "d818c08028f7284caf8646e0c27cf4cea3fec0c0abaeaa54f714b7cba57dccf3"
    },
    {
      "event_id": "52894e23e8194e0d95bcb5ea648e92d2",
      "session_id": "47a2b7a2e1cd452fadf5a9309112ccd5",
      "step": 5,
      "type": "llm_call",
      "payload": {
        "args": {
          "messages": [
            {
              "content": "Fix sample_pkg.stats.mean so that the test suite passes.",
              "role": "user"
            },
            {
              "content": {
                "args": {
                  "path": "sample_pkg/stats.py"
                },
                "tool": "read_file"
              },
              "role": "assistant"
            },
            {
              "content": {
                "content": "\"\"\"Statistics helpers.\"\"\"\n\n\ndef mean(values: list[float]) -> float:\n    \"\"\"Return the arithmetic mean of values.\"\"\"\n    return sum(values) / (len(values) - 1)\n",
                "path": "sample_pkg/stats.py"
              },
              "name": "read_file",
              "role": "tool"
            }
          ],
          "turn": 1
        },
        "fingerprint": "7cacb714a0fb31b1410558c35d62ced9b869ed6a710b6fb1062766ce6a9308cf",
        "name": "llm"
      },
      "timestamp": "2026-11-25T16:31:45.369063+00:00",
      "parent_step": null,
      "prev_hash": "d818c08028f7284caf8646e0c27cf4cea3fec0c0abaeaa54f714b7cba57dccf3",
      "hash": "1242848e04efee9bafab1ae627245c744c1ea9ad49a96a10a865d851451c15fc"
    },
    {
      "event_id": "741ea862c9df4f1f84131a82aad7842d",
      "session_id": "47a2b7a2e1cd452fadf5a9309112ccd5",
      "step": 6,
      "type": "tool_result",
      "payload": {
        "name": "llm",
        "result": {
          "args": {
            "content": "\"\"\"Statistics helpers.\"\"\"\n\n\ndef mean(values: list[float]) -> float:\n    \"\"\"Return the arithmetic mean of values.\"\"\"\n    return sum(values) / len(values) - 1\n",
            "path": "sample_pkg/stats.py"
          },
          "tool": "write_file"
        }
      },
      "timestamp": "2026-11-25T16:31:45.444404+00:00",
      "parent_step": 5,
      "prev_hash": "1242848e04efee9bafab1ae627245c744c1ea9ad49a96a10a865d851451c15fc",
      "hash": "1566733597854c47c864ec9641442346ad7e1d669598e00d7e07e634433846fb"
    },
    {
      "event_id": "57e69caf5ed84f6f88b553a76dda7070",
      "session_id": "47a2b7a2e1cd452fadf5a9309112ccd5",
      "step": 7,
      "type": "tool_call",
      "payload": {
        "args": {
          "content": "\"\"\"Statistics helpers.\"\"\"\n\n\ndef mean(values: list[float]) -> float:\n    \"\"\"Return the arithmetic mean of values.\"\"\"\n    return sum(values) / len(values) - 1\n",
          "path": "sample_pkg/stats.py"
        },
        "fingerprint": "e39a1678ed7a453635662b4ac31cbd5f27c5c8ab09ea2d76f80b6aba25f91591",
        "name": "write_file"
      },
      "timestamp": "2026-11-25T16:31:45.546965+00:00",
      "parent_step": null,
      "prev_hash": "1566733597854c47c864ec9641442346ad7e1d669598e00d7e07e634433846fb",
      "hash": "a8ce7ec99869ffe8c870057582ac92a2475bb61746702079a29ce329e6dea2dc"
    },
    {
      "event_id": "caed93cf32df475a86fd938fa7dcd941",
      "session_id": "47a2b7a2e1cd452fadf5a9309112ccd5",
      "step": 8,
      "type": "tool_result",
      "payload": {
        "name": "write_file",
        "result": {
          "bytes": 157,
          "path": "sample_pkg/stats.py"
        }
      },
      "timestamp": "2026-11-25T16:31:45.673933+00:00",
      "parent_step": 7,
      "prev_hash": "a8ce7ec99869ffe8c870057582ac92a2475bb61746702079a29ce329e6dea2dc",
      "hash": "547dcf1a12d12570522b63a18c2f5c24660d3032ec96d683ea77c0a3e9c335ba"
    },
    {
      "event_id": "97764334b30f4035af2137419996a096",
      "session_id": "47a2b7a2e1cd452fadf5a9309112ccd5",
      "step": 9,
      "type": "llm_call",
      "payload": {
        "args": {
          "messages": [
            {
              "content": "Fix sample_pkg.stats.mean so that the test suite passes.",
              "role": "user"
            },
            {
              "content": {
                "args": {
                  "path": "sample_pkg/stats.py"
                },
                "tool": "read_file"
              },
              "role": "assistant"
            },
            {
              "content": {
                "content": "\"\"\"Statistics helpers.\"\"\"\n\n\ndef mean(values: list[float]) -> float:\n    \"\"\"Return the arithmetic mean of values.\"\"\"\n    return sum(values) / (len(values) - 1)\n",
                "path": "sample_pkg/stats.py"
              },
              "name": "read_file",
              "role": "tool"
            },
            {
              "content": {
                "args": {
                  "content": "\"\"\"Statistics helpers.\"\"\"\n\n\ndef mean(values: list[float]) -> float:\n    \"\"\"Return the arithmetic mean of values.\"\"\"\n    return sum(values) / len(values) - 1\n",
                  "path": "sample_pkg/stats.py"
                },
                "tool": "write_file"
              },
              "role": "assistant"
            },
            {
              "content": {
                "bytes": 157,
                "path": "sample_pkg/stats.py"
              },
              "name": "write_file",
              "role": "tool"
            }
          ],
          "turn": 2
        },
        "fingerprint": "4fa6694c6697d13f2cd9d86495bb7978ebcbfe7c92aa6cc4c1e3a950a6251f45",
        "name": "llm"
      },
      "timestamp": "2026-11-25T16:31:45.771876+00:00",
      "parent_step": null,
      "prev_hash": "547dcf1a12d12570522b63a18c2f5c24660d3032ec96d683ea77c0a3e9c335ba",
      "hash": "16a9ee6ecb6c0a2d9e352797159f68b103871a68dea13a091fd21571cfd6c1e9"
    },
    {
      "event_id": "ded60d9b8bbb4aa0a4b3658647444e8c",
      "session_id": "47a2b7a2e1cd452fadf5a9309112ccd5",
      "step": 10,
      "type": "tool_result",
      "payload": {
        "name": "llm",
        "result": {
          "args": {},
          "tool": "run_tests"
        }
      },
      "timestamp": "2026-11-25T16:31:45.837840+00:00",
      "parent_step": 9,
      "prev_hash": "16a9ee6ecb6c0a2d9e352797159f68b103871a68dea13a091fd21571cfd6c1e9",
      "hash": "191dc972b95c7897329932c82c06d02b1e59cfdfbfc651c9940401fd27a04578"
    },
    {
      "event_id": "4c1d07ab2ff049f49791d6df09dcb4c9",
      "session_id": "47a2b7a2e1cd452fadf5a9309112ccd5",
      "step": 11,
      "type": "tool_call",
      "payload": {
        "args": {},
        "fingerprint": "352eb86387c09c5cd8eebbeb17ec318844802b1745800432ecc2e473a3f7bfa2",
        "name": "run_tests"
      },
      "timestamp": "2026-11-25T16:31:54.391105+00:00",
      "parent_step": null,
      "prev_hash": "191dc972b95c7897329932c82c06d02b1e59cfdfbfc651c9940401fd27a04578",
      "hash": "5938912d11a2e610eb961bfe1080eaa04625938c25d902540a74a5472cfca0ef"
    },
    {
      "event_id": "a0de6d6594844ae9862b9087586daf30",
      "session_id": "47a2b7a2e1cd452fadf5a9309112ccd5",
      "step": 12,
      "type": "tool_result",
      "payload": {
        "name": "run_tests",
        "result": {
          "exit_code": 1,
          "failed": 1,
          "failed_tests": [
            "tests/test_stats.py::test_mean_of_three"
          ],
          "passed": 2
        }
      },
      "timestamp": "2026-11-25T16:31:54.438074+00:00",
      "parent_step": 11,
      "prev_hash": "5938912d11a2e610eb961bfe1080eaa04625938c25d902540a74a5472cfca0ef",
      "hash": "cba84cc27098976ca45c6135b0a711985f802ec15c44156fa81f1e557a9ca365"
    },
    {
      "event_id": "5459018a6f0e4e2ca979353e117a4372",
      "session_id": "47a2b7a2e1cd452fadf5a9309112ccd5",
      "step": 13,
      "type": "llm_call",
      "payload": {
        "args": {
          "messages": [
            {
              "content": "Fix sample_pkg.stats.mean so that the test suite passes.",
              "role": "user"
            },
            {
              "content": {
                "args": {
                  "path": "sample_pkg/stats.py"
                },
                "tool": "read_file"
              },
              "role": "assistant"
            },
            {
              "content": {
                "content": "\"\"\"Statistics helpers.\"\"\"\n\n\ndef mean(values: list[float]) -> float:\n    \"\"\"Return the arithmetic mean of values.\"\"\"\n    return sum(values) / (len(values) - 1)\n",
                "path": "sample_pkg/stats.py"
              },
              "name": "read_file",
              "role": "tool"
            },
            {
              "content": {
                "args": {
                  "content": "\"\"\"Statistics helpers.\"\"\"\n\n\ndef mean(values: list[float]) -> float:\n    \"\"\"Return the arithmetic mean of values.\"\"\"\n    return sum(values) / len(values) - 1\n",
                  "path": "sample_pkg/stats.py"
                },
                "tool": "write_file"
              },
              "role": "assistant"
            },
            {
              "content": {
                "bytes": 157,
                "path": "sample_pkg/stats.py"
              },
              "name": "write_file",
              "role": "tool"
            },
            {
              "content": {
                "args": {},
                "tool": "run_tests"
              },
              "role": "assistant"
            },
            {
              "content": {
                "exit_code": 1,
                "failed": 1,
                "failed_tests": [
                  "tests/test_stats.py::test_mean_of_three"
                ],
                "passed": 2
              },
              "name": "run_tests",
              "role": "tool"
            }
          ],
          "turn": 3
        },
        "fingerprint": "a345536dc0346f20da294d6e52486c19b3732fcdb933381cf4fa831406e01dcf",
        "name": "llm"
      },
      "timestamp": "2026-11-25T16:31:54.504036+00:00",
      "parent_step": null,
      "prev_hash": "cba84cc27098976ca45c6135b0a711985f802ec15c44156fa81f1e557a9ca365",
      "hash": "3d52615678bfe12cdb854b24803ddfbb316b4ac26458a5636974ddf40191c6f9"
    },
    {
      "event_id": "dcb0eac074904bbaaf69fd10eb602873",
      "session_id": "47a2b7a2e1cd452fadf5a9309112ccd5",
      "step": 14,
      "type": "tool_result",
      "payload": {
        "name": "llm",
        "result": {
          "args": {
            "content": "\"\"\"Statistics helpers.\"\"\"\n\n\ndef mean(values: list[float]) -> float:\n    \"\"\"Return the arithmetic mean of values.\"\"\"\n    return sum(values) / len(values)\n",
            "path": "sample_pkg/stats.py"
          },
          "tool": "write_file"
        }
      },
      "timestamp": "2026-11-25T16:31:54.560004+00:00",
      "parent_step": 13,
      "prev_hash": "3d52615678bfe12cdb854b24803ddfbb316b4ac26458a5636974ddf40191c6f9",
      "hash": "95cfc1678b6e0419728d91ac710cc33a69d171043d533d3996c1d8100eed2aab"
    },
    {
      "event_id": "16433309bcbb471789695e9c77856f88",
      "session_id": "47a2b7a2e1cd452fadf5a9309112ccd5",
      "step": 15,
      "type": "tool_call",
      "payload": {
        "args": {
          "content": "\"\"\"Statistics helpers.\"\"\"\n\n\ndef mean(values: list[float]) -> float:\n    \"\"\"Return the arithmetic mean of values.\"\"\"\n    return sum(values) / len(values)\n",
          "path": "sample_pkg/stats.py"
        },
        "fingerprint": "378073a36f5a4e7b0188322ccd789c7cc1d0db2eeb2b6788b80f938d4fa621da",
        "name": "write_file"
      },
      "timestamp": "2026-11-25T16:31:54.716915+00:00",
      "parent_step": null,
      "prev_hash": "95cfc1678b6e0419728d91ac710cc33a69d171043d533d3996c1d8100eed2aab",
      "hash": "fc26d6ed93f39569f4a16aa248076ee46541d3fc016cc98de74c9ffdfc38c16f"
    },
    {
      "event_id": "e6c2619aae5e43f582d1086334faa4ba",
      "session_id": "47a2b7a2e1cd452fadf5a9309112ccd5",
      "step": 16,
      "type": "tool_result",
      "payload": {
        "name": "write_file",
        "result": {
          "bytes": 153,
          "path": "sample_pkg/stats.py"
        }
      },
      "timestamp": "2026-11-25T16:31:54.857833+00:00",
      "parent_step": 15,
      "prev_hash": "fc26d6ed93f39569f4a16aa248076ee46541d3fc016cc98de74c9ffdfc38c16f",
      "hash": "517eb7adce6a3eee02e4d2e80a0c8752eb7f4bfc6adb168711da244b9d5e394d"
    },
    {
      "event_id": "b855bd92d6a846fe8d3e075fafb87da2",
      "session_id": "47a2b7a2e1cd452fadf5a9309112ccd5",
      "step": 17,
      "type": "llm_call",
      "payload": {
        "args": {
          "messages": [
            {
              "content": "Fix sample_pkg.stats.mean so that the test suite passes.",
              "role": "user"
            },
            {
              "content": {
                "args": {
                  "path": "sample_pkg/stats.py"
                },
                "tool": "read_file"
              },
              "role": "assistant"
            },
            {
              "content": {
                "content": "\"\"\"Statistics helpers.\"\"\"\n\n\ndef mean(values: list[float]) -> float:\n    \"\"\"Return the arithmetic mean of values.\"\"\"\n    return sum(values) / (len(values) - 1)\n",
                "path": "sample_pkg/stats.py"
              },
              "name": "read_file",
              "role": "tool"
            },
            {
              "content": {
                "args": {
                  "content": "\"\"\"Statistics helpers.\"\"\"\n\n\ndef mean(values: list[float]) -> float:\n    \"\"\"Return the arithmetic mean of values.\"\"\"\n    return sum(values) / len(values) - 1\n",
                  "path": "sample_pkg/stats.py"
                },
                "tool": "write_file"
              },
              "role": "assistant"
            },
            {
              "content": {
                "bytes": 157,
                "path": "sample_pkg/stats.py"
              },
              "name": "write_file",
              "role": "tool"
            },
            {
              "content": {
                "args": {},
                "tool": "run_tests"
              },
              "role": "assistant"
            },
            {
              "content": {
                "exit_code": 1,
                "failed": 1,
                "failed_tests": [
                  "tests/test_stats.py::test_mean_of_three"
                ],
                "passed": 2
              },
              "name": "run_tests",
              "role": "tool"
            },
            {
              "content": {
                "args": {
                  "content": "\"\"\"Statistics helpers.\"\"\"\n\n\ndef mean(values: list[float]) -> float:\n    \"\"\"Return the arithmetic mean of values.\"\"\"\n    return sum(values) / len(values)\n",
                  "path": "sample_pkg/stats.py"
                },
                "tool": "write_file"
              },
              "role": "assistant"
            },
            {
              "content": {
                "bytes": 153,
                "path": "sample_pkg/stats.py"
              },
              "name": "write_file",
              "role": "tool"
            }
          ],
          "turn": 4
        },
        "fingerprint": "0ecf530909d181404738659f09290fb00bcebe2b2beb1d213ddb86103bcc582d",
        "name": "llm"
      },
      "timestamp": "2026-11-25T16:31:54.924793+00:00",
      "parent_step": null,
      "prev_hash": "517eb7adce6a3eee02e4d2e80a0c8752eb7f4bfc6adb168711da244b9d5e394d",
      "hash": "af1383eca929925e25bdb34cfe316c85242dcce09c15f1714671c971736b084a"
    },
    {
      "event_id": "59663e68e9d64a608672340472222102",
      "session_id": "47a2b7a2e1cd452fadf5a9309112ccd5",
      "step": 18,
      "type": "tool_result",
      "payload": {
        "name": "llm",
        "result": {
          "args": {},
          "tool": "run_tests"
        }
      },
      "timestamp": "2026-11-25T16:31:55.055718+00:00",
      "parent_step": 17,
      "prev_hash": "af1383eca929925e25bdb34cfe316c85242dcce09c15f1714671c971736b084a",
      "hash": "8dcee05c0feec671982344842f29e8ce24fb4e80d54f061b25cddf2514a6ae57"
    },
    {
      "event_id": "b682779f40f14e2b9315521f15e2dff9",
      "session_id": "47a2b7a2e1cd452fadf5a9309112ccd5",
      "step": 19,
      "type": "tool_call",
      "payload": {
        "args": {},
        "fingerprint": "352eb86387c09c5cd8eebbeb17ec318844802b1745800432ecc2e473a3f7bfa2",
        "name": "run_tests"
      },
      "timestamp": "2026-11-25T16:31:58.177262+00:00",
      "parent_step": null,
      "prev_hash": "8dcee05c0feec671982344842f29e8ce24fb4e80d54f061b25cddf2514a6ae57",
      "hash": "1ea8db8694f8f7d9da6a911140dadf7f2d898c9184a3418faa24aff4ee20bd16"
    },
    {
      "event_id": "c86fe0c4de1245df996d0c54e160ce46",
      "session_id": "47a2b7a2e1cd452fadf5a9309112ccd5",
      "step": 20,
      "type": "tool_result",
      "payload": {
        "name": "run_tests",
        "result": {
          "exit_code": 0,
          "failed": 0,
          "failed_tests": [],
          "passed": 3
        }
      },
      "timestamp": "2026-11-25T16:31:58.489081+00:00",
      "parent_step": 19,
      "prev_hash": "1ea8db8694f8f7d9da6a911140dadf7f2d898c9184a3418faa24aff4ee20bd16",
      "hash": "7f76c3fa849da53955c0a69dbd39515335ab74182317fc2240f80ee39fc223fe"
    },
    {
      "event_id": "55fe133f69e14d81b5572b4f3b383ed9",
      "session_id": "47a2b7a2e1cd452fadf5a9309112ccd5",
      "step": 21,
      "type": "llm_call",
      "payload": {
        "args": {
          "messages": [
            {
              "content": "Fix sample_pkg.stats.mean so that the test suite passes.",
              "role": "user"
            },
            {
              "content": {
                "args": {
                  "path": "sample_pkg/stats.py"
                },
                "tool": "read_file"
              },
              "role": "assistant"
            },
            {
              "content": {
                "content": "\"\"\"Statistics helpers.\"\"\"\n\n\ndef mean(values: list[float]) -> float:\n    \"\"\"Return the arithmetic mean of values.\"\"\"\n    return sum(values) / (len(values) - 1)\n",
                "path": "sample_pkg/stats.py"
              },
              "name": "read_file",
              "role": "tool"
            },
            {
              "content": {
                "args": {
                  "content": "\"\"\"Statistics helpers.\"\"\"\n\n\ndef mean(values: list[float]) -> float:\n    \"\"\"Return the arithmetic mean of values.\"\"\"\n    return sum(values) / len(values) - 1\n",
                  "path": "sample_pkg/stats.py"
                },
                "tool": "write_file"
              },
              "role": "assistant"
            },
            {
              "content": {
                "bytes": 157,
                "path": "sample_pkg/stats.py"
              },
              "name": "write_file",
              "role": "tool"
            },
            {
              "content": {
                "args": {},
                "tool": "run_tests"
              },
              "role": "assistant"
            },
            {
              "content": {
                "exit_code": 1,
                "failed": 1,
                "failed_tests": [
                  "tests/test_stats.py::test_mean_of_three"
                ],
                "passed": 2
              },
              "name": "run_tests",
              "role": "tool"
            },
            {
              "content": {
                "args": {
                  "content": "\"\"\"Statistics helpers.\"\"\"\n\n\ndef mean(values: list[float]) -> float:\n    \"\"\"Return the arithmetic mean of values.\"\"\"\n    return sum(values) / len(values)\n",
                  "path": "sample_pkg/stats.py"
                },
                "tool": "write_file"
              },
              "role": "assistant"
            },
            {
              "content": {
                "bytes": 153,
                "path": "sample_pkg/stats.py"
              },
              "name": "write_file",
              "role": "tool"
            },
            {
              "content": {
                "args": {},
                "tool": "run_tests"
              },
              "role": "assistant"
            },
            {
              "content": {
                "exit_code": 0,
                "failed": 0,
                "failed_tests": [],
                "passed": 3
              },
              "name": "run_tests",
              "role": "tool"
            }
          ],
          "turn": 5
        },
        "fingerprint": "c81e502f7222fabc9d96e3fff37f33c921e8638f5b4d24cd8b8ca2a6a5fe346c",
        "name": "llm"
      },
      "timestamp": "2026-11-25T16:31:58.632999+00:00",
      "parent_step": null,
      "prev_hash": "7f76c3fa849da53955c0a69dbd39515335ab74182317fc2240f80ee39fc223fe",
      "hash": "fc7149842516b9cce1acba09ab35d670d51ee760b17c0fef4e7918062bdcd328"
    },
    {
      "event_id": "293483fc4e664655aba33f0538a95edb",
      "session_id": "47a2b7a2e1cd452fadf5a9309112ccd5",
      "step": 22,
      "type": "tool_result",
      "payload": {
        "name": "llm",
        "result": {
          "final": "Divide by len(values) in mean."
        }
      },
      "timestamp": "2026-11-25T16:31:58.806899+00:00",
      "parent_step": 21,
      "prev_hash": "fc7149842516b9cce1acba09ab35d670d51ee760b17c0fef4e7918062bdcd328",
      "hash": "37b2ce08db11858ded2e24f2fa61ac89591cbc8c85271270acf8131631ddbdab"
    },
    {
      "event_id": "97e8bbb99cf84e72982c5c52ed656c2d",
      "session_id": "47a2b7a2e1cd452fadf5a9309112ccd5",
      "step": 23,
      "type": "final_answer",
      "payload": {
        "value": {
          "answer": "Divide by len(values) in mean."
        }
      },
      "timestamp": "2026-11-25T16:31:58.925830+00:00",
      "parent_step": null,
      "prev_hash": "37b2ce08db11858ded2e24f2fa61ac89591cbc8c85271270acf8131631ddbdab",
      "hash": "2a1927b8272cca44e2818eb64943db2239bf22ba4d2d483805b7d3ce26b206bc"
    }
  ]
}
```

`events` lists every stored event in step order. Each event has the fields of the core `Event`
model: `event_id`, `session_id`, `step`, `type`, `payload`, `timestamp`, `parent_step`,
`prev_hash`, `hash`. Payloads are already redacted by the core. Raises `SessionNotFoundError` for
an unknown id.

## `replay_summary(store, session_id, *, workspace_root)`

```json
{
  "session_id": "47a2b7a2e1cd452fadf5a9309112ccd5",
  "final": "Divide by len(values) in mean.",
  "replay_counters": {
    "llm": 0,
    "read_file": 0,
    "write_file": 0,
    "run_tests": 0
  },
  "matches_recorded": true
}
```

`replay_counters` counts the real calls made during the replay. It must be all 0.
`matches_recorded` is true when the replayed final answer equals the answer stored by the
`final_answer` event.

## `find_bad_edit(store, session_id)`

```json
{
  "session_id": "47a2b7a2e1cd452fadf5a9309112ccd5",
  "bad_edit": {
    "step": 7,
    "path": "sample_pkg/stats.py"
  }
}
```

When no write is bad, `bad_edit` is `null`.

A bad edit is a `write_file` call after which the next recorded `run_tests` result exits non-zero,
with no other write in between. The verdict comes only from recorded results. `step` is the step
of the `write_file` call event.

## `fork(store, parent_session_id, at_step, *, override=None, use_override=False)`

Requires `use_override=True`. Without it the call raises `ForkNotSupportedError`.

```json
{
  "child_session_id": "6562a249689f48a08957b23be2ca6e1c",
  "diff": {
    "first_divergent_step": 8,
    "kind": "result",
    "differing_steps": [
      {
        "step": 8,
        "kind": "result",
        "a": {
          "type": "tool_result",
          "parent_step": 7,
          "payload": {
            "name": "write_file",
            "result": {
              "bytes": 157,
              "path": "sample_pkg/stats.py"
            }
          }
        },
        "b": {
          "type": "tool_result",
          "parent_step": 7,
          "payload": {
            "name": "write_file",
            "overridden": true,
            "result": {
              "ok": true
            }
          }
        }
      },
      {
        "step": 9,
        "kind": "length",
        "a": {
          "type": "llm_call",
          "parent_step": null,
          "payload": {
            "args": {
              "messages": [
                {
                  "content": "Fix sample_pkg.stats.mean so that the test suite passes.",
                  "role": "user"
                },
                {
                  "content": {
                    "args": {
                      "path": "sample_pkg/stats.py"
                    },
                    "tool": "read_file"
                  },
                  "role": "assistant"
                },
                {
                  "content": {
                    "content": "\"\"\"Statistics helpers.\"\"\"\n\n\ndef mean(values: list[float]) -> float:\n    \"\"\"Return the arithmetic mean of values.\"\"\"\n    return sum(values) / (len(values) - 1)\n",
                    "path": "sample_pkg/stats.py"
                  },
                  "name": "read_file",
                  "role": "tool"
                },
                {
                  "content": {
                    "args": {
                      "content": "\"\"\"Statistics helpers.\"\"\"\n\n\ndef mean(values: list[float]) -> float:\n    \"\"\"Return the arithmetic mean of values.\"\"\"\n    return sum(values) / len(values) - 1\n",
                      "path": "sample_pkg/stats.py"
                    },
                    "tool": "write_file"
                  },
                  "role": "assistant"
                },
                {
                  "content": {
                    "bytes": 157,
                    "path": "sample_pkg/stats.py"
                  },
                  "name": "write_file",
                  "role": "tool"
                }
              ],
              "turn": 2
            },
            "fingerprint": "4fa6694c6697d13f2cd9d86495bb7978ebcbfe7c92aa6cc4c1e3a950a6251f45",
            "name": "llm"
          }
        },
        "b": null
      },
      {
        "step": 10,
        "kind": "length",
        "a": {
          "type": "tool_result",
          "parent_step": 9,
          "payload": {
            "name": "llm",
            "result": {
              "args": {},
              "tool": "run_tests"
            }
          }
        },
        "b": null
      },
      {
        "step": 11,
        "kind": "length",
        "a": {
          "type": "tool_call",
          "parent_step": null,
          "payload": {
            "args": {},
            "fingerprint": "352eb86387c09c5cd8eebbeb17ec318844802b1745800432ecc2e473a3f7bfa2",
            "name": "run_tests"
          }
        },
        "b": null
      },
      {
        "step": 12,
        "kind": "length",
        "a": {
          "type": "tool_result",
          "parent_step": 11,
          "payload": {
            "name": "run_tests",
            "result": {
              "exit_code": 1,
              "failed": 1,
              "failed_tests": [
                "tests/test_stats.py::test_mean_of_three"
              ],
              "passed": 2
            }
          }
        },
        "b": null
      },
      {
        "step": 13,
        "kind": "length",
        "a": {
          "type": "llm_call",
          "parent_step": null,
          "payload": {
            "args": {
              "messages": [
                {
                  "content": "Fix sample_pkg.stats.mean so that the test suite passes.",
                  "role": "user"
                },
                {
                  "content": {
                    "args": {
                      "path": "sample_pkg/stats.py"
                    },
                    "tool": "read_file"
                  },
                  "role": "assistant"
                },
                {
                  "content": {
                    "content": "\"\"\"Statistics helpers.\"\"\"\n\n\ndef mean(values: list[float]) -> float:\n    \"\"\"Return the arithmetic mean of values.\"\"\"\n    return sum(values) / (len(values) - 1)\n",
                    "path": "sample_pkg/stats.py"
                  },
                  "name": "read_file",
                  "role": "tool"
                },
                {
                  "content": {
                    "args": {
                      "content": "\"\"\"Statistics helpers.\"\"\"\n\n\ndef mean(values: list[float]) -> float:\n    \"\"\"Return the arithmetic mean of values.\"\"\"\n    return sum(values) / len(values) - 1\n",
                      "path": "sample_pkg/stats.py"
                    },
                    "tool": "write_file"
                  },
                  "role": "assistant"
                },
                {
                  "content": {
                    "bytes": 157,
                    "path": "sample_pkg/stats.py"
                  },
                  "name": "write_file",
                  "role": "tool"
                },
                {
                  "content": {
                    "args": {},
                    "tool": "run_tests"
                  },
                  "role": "assistant"
                },
                {
                  "content": {
                    "exit_code": 1,
                    "failed": 1,
                    "failed_tests": [
                      "tests/test_stats.py::test_mean_of_three"
                    ],
                    "passed": 2
                  },
                  "name": "run_tests",
                  "role": "tool"
                }
              ],
              "turn": 3
            },
            "fingerprint": "a345536dc0346f20da294d6e52486c19b3732fcdb933381cf4fa831406e01dcf",
            "name": "llm"
          }
        },
        "b": null
      },
      {
        "step": 14,
        "kind": "length",
        "a": {
          "type": "tool_result",
          "parent_step": 13,
          "payload": {
            "name": "llm",
            "result": {
              "args": {
                "content": "\"\"\"Statistics helpers.\"\"\"\n\n\ndef mean(values: list[float]) -> float:\n    \"\"\"Return the arithmetic mean of values.\"\"\"\n    return sum(values) / len(values)\n",
                "path": "sample_pkg/stats.py"
              },
              "tool": "write_file"
            }
          }
        },
        "b": null
      },
      {
        "step": 15,
        "kind": "length",
        "a": {
          "type": "tool_call",
          "parent_step": null,
          "payload": {
            "args": {
              "content": "\"\"\"Statistics helpers.\"\"\"\n\n\ndef mean(values: list[float]) -> float:\n    \"\"\"Return the arithmetic mean of values.\"\"\"\n    return sum(values) / len(values)\n",
              "path": "sample_pkg/stats.py"
            },
            "fingerprint": "378073a36f5a4e7b0188322ccd789c7cc1d0db2eeb2b6788b80f938d4fa621da",
            "name": "write_file"
          }
        },
        "b": null
      },
      {
        "step": 16,
        "kind": "length",
        "a": {
          "type": "tool_result",
          "parent_step": 15,
          "payload": {
            "name": "write_file",
            "result": {
              "bytes": 153,
              "path": "sample_pkg/stats.py"
            }
          }
        },
        "b": null
      },
      {
        "step": 17,
        "kind": "length",
        "a": {
          "type": "llm_call",
          "parent_step": null,
          "payload": {
            "args": {
              "messages": [
                {
                  "content": "Fix sample_pkg.stats.mean so that the test suite passes.",
                  "role": "user"
                },
                {
                  "content": {
                    "args": {
                      "path": "sample_pkg/stats.py"
                    },
                    "tool": "read_file"
                  },
                  "role": "assistant"
                },
                {
                  "content": {
                    "content": "\"\"\"Statistics helpers.\"\"\"\n\n\ndef mean(values: list[float]) -> float:\n    \"\"\"Return the arithmetic mean of values.\"\"\"\n    return sum(values) / (len(values) - 1)\n",
                    "path": "sample_pkg/stats.py"
                  },
                  "name": "read_file",
                  "role": "tool"
                },
                {
                  "content": {
                    "args": {
                      "content": "\"\"\"Statistics helpers.\"\"\"\n\n\ndef mean(values: list[float]) -> float:\n    \"\"\"Return the arithmetic mean of values.\"\"\"\n    return sum(values) / len(values) - 1\n",
                      "path": "sample_pkg/stats.py"
                    },
                    "tool": "write_file"
                  },
                  "role": "assistant"
                },
                {
                  "content": {
                    "bytes": 157,
                    "path": "sample_pkg/stats.py"
                  },
                  "name": "write_file",
                  "role": "tool"
                },
                {
                  "content": {
                    "args": {},
                    "tool": "run_tests"
                  },
                  "role": "assistant"
                },
                {
                  "content": {
                    "exit_code": 1,
                    "failed": 1,
                    "failed_tests": [
                      "tests/test_stats.py::test_mean_of_three"
                    ],
                    "passed": 2
                  },
                  "name": "run_tests",
                  "role": "tool"
                },
                {
                  "content": {
                    "args": {
                      "content": "\"\"\"Statistics helpers.\"\"\"\n\n\ndef mean(values: list[float]) -> float:\n    \"\"\"Return the arithmetic mean of values.\"\"\"\n    return sum(values) / len(values)\n",
                      "path": "sample_pkg/stats.py"
                    },
                    "tool": "write_file"
                  },
                  "role": "assistant"
                },
                {
                  "content": {
                    "bytes": 153,
                    "path": "sample_pkg/stats.py"
                  },
                  "name": "write_file",
                  "role": "tool"
                }
              ],
              "turn": 4
            },
            "fingerprint": "0ecf530909d181404738659f09290fb00bcebe2b2beb1d213ddb86103bcc582d",
            "name": "llm"
          }
        },
        "b": null
      },
      {
        "step": 18,
        "kind": "length",
        "a": {
          "type": "tool_result",
          "parent_step": 17,
          "payload": {
            "name": "llm",
            "result": {
              "args": {},
              "tool": "run_tests"
            }
          }
        },
        "b": null
      },
      {
        "step": 19,
        "kind": "length",
        "a": {
          "type": "tool_call",
          "parent_step": null,
          "payload": {
            "args": {},
            "fingerprint": "352eb86387c09c5cd8eebbeb17ec318844802b1745800432ecc2e473a3f7bfa2",
            "name": "run_tests"
          }
        },
        "b": null
      },
      {
        "step": 20,
        "kind": "length",
        "a": {
          "type": "tool_result",
          "parent_step": 19,
          "payload": {
            "name": "run_tests",
            "result": {
              "exit_code": 0,
              "failed": 0,
              "failed_tests": [],
              "passed": 3
            }
          }
        },
        "b": null
      },
      {
        "step": 21,
        "kind": "length",
        "a": {
          "type": "llm_call",
          "parent_step": null,
          "payload": {
            "args": {
              "messages": [
                {
                  "content": "Fix sample_pkg.stats.mean so that the test suite passes.",
                  "role": "user"
                },
                {
                  "content": {
                    "args": {
                      "path": "sample_pkg/stats.py"
                    },
                    "tool": "read_file"
                  },
                  "role": "assistant"
                },
                {
                  "content": {
                    "content": "\"\"\"Statistics helpers.\"\"\"\n\n\ndef mean(values: list[float]) -> float:\n    \"\"\"Return the arithmetic mean of values.\"\"\"\n    return sum(values) / (len(values) - 1)\n",
                    "path": "sample_pkg/stats.py"
                  },
                  "name": "read_file",
                  "role": "tool"
                },
                {
                  "content": {
                    "args": {
                      "content": "\"\"\"Statistics helpers.\"\"\"\n\n\ndef mean(values: list[float]) -> float:\n    \"\"\"Return the arithmetic mean of values.\"\"\"\n    return sum(values) / len(values) - 1\n",
                      "path": "sample_pkg/stats.py"
                    },
                    "tool": "write_file"
                  },
                  "role": "assistant"
                },
                {
                  "content": {
                    "bytes": 157,
                    "path": "sample_pkg/stats.py"
                  },
                  "name": "write_file",
                  "role": "tool"
                },
                {
                  "content": {
                    "args": {},
                    "tool": "run_tests"
                  },
                  "role": "assistant"
                },
                {
                  "content": {
                    "exit_code": 1,
                    "failed": 1,
                    "failed_tests": [
                      "tests/test_stats.py::test_mean_of_three"
                    ],
                    "passed": 2
                  },
                  "name": "run_tests",
                  "role": "tool"
                },
                {
                  "content": {
                    "args": {
                      "content": "\"\"\"Statistics helpers.\"\"\"\n\n\ndef mean(values: list[float]) -> float:\n    \"\"\"Return the arithmetic mean of values.\"\"\"\n    return sum(values) / len(values)\n",
                      "path": "sample_pkg/stats.py"
                    },
                    "tool": "write_file"
                  },
                  "role": "assistant"
                },
                {
                  "content": {
                    "bytes": 153,
                    "path": "sample_pkg/stats.py"
                  },
                  "name": "write_file",
                  "role": "tool"
                },
                {
                  "content": {
                    "args": {},
                    "tool": "run_tests"
                  },
                  "role": "assistant"
                },
                {
                  "content": {
                    "exit_code": 0,
                    "failed": 0,
                    "failed_tests": [],
                    "passed": 3
                  },
                  "name": "run_tests",
                  "role": "tool"
                }
              ],
              "turn": 5
            },
            "fingerprint": "c81e502f7222fabc9d96e3fff37f33c921e8638f5b4d24cd8b8ca2a6a5fe346c",
            "name": "llm"
          }
        },
        "b": null
      },
      {
        "step": 22,
        "kind": "length",
        "a": {
          "type": "tool_result",
          "parent_step": 21,
          "payload": {
            "name": "llm",
            "result": {
              "final": "Divide by len(values) in mean."
            }
          }
        },
        "b": null
      },
      {
        "step": 23,
        "kind": "length",
        "a": {
          "type": "final_answer",
          "parent_step": null,
          "payload": {
            "value": {
              "answer": "Divide by len(values) in mean."
            }
          }
        },
        "b": null
      }
    ],
    "len_a": 24,
    "len_b": 9
  }
}
```

`child_session_id` is the new session. Its `parent_session_id` and `parent_step` link it to the
parent. `diff` compares the parent with the child, step by step:

- `first_divergent_step`: the first step that differs, or `null`.
- `kind`: `different_tool`, `args`, `result`, `length`, or `null`.
- `differing_steps`: every step that differs. Each has `step`, `kind`, and the `a` and `b` views.
- `len_a` and `len_b`: the event counts of the parent and the child.

The fork replays the parent up to `at_step` and records the call at `at_step` with `override` as
its result. It makes no live call and writes no file. The parent is not changed. `at_step` must
be a `llm_call` or `tool_call` step, otherwise the core raises `InvalidForkPointError`.

## Fork override shapes

`override` takes any JSON value: `null`, `true` or `false`, finite numbers, strings, arrays, and
objects with string keys. Values may nest.

These are rejected with 400: `NaN`, `Infinity` and `-Infinity`, because they are not valid JSON.
From Python, a value that is not plain JSON (a tuple, set, bytes or a custom object) raises
`PayloadSerializationError`. A JSON request body cannot carry such a value.

`use_override` is the only switch that applies an override. A request that sends `override`
without `"use_override": true` fails with 400, and no child session is created.

```json
{"at_step": 7, "override": {"ok": true}, "use_override": true}
{"at_step": 7, "override": null, "use_override": true}
```

The core redacts the override before it stores it. Values under the keys `api_key`, `password`,
`token`, `secret`, `authorization`, `cookie`, `bearer` and `private_key` become `"[REDACTED]"` at
any depth, and secrets written as `key=value` inside strings are masked. The `diff` returned by
`fork` shows the stored value, so it can differ from the value that was sent.

## Errors (Python)

| Error | Raised when |
|---|---|
| `SessionNotFoundError` (core) | the session id is unknown |
| `InvalidForkPointError` (core) | `at_step` is not a call step of the parent |
| `ForkNotSupportedError` | `fork` is called without `use_override=True` |
| `PayloadSerializationError` (core) | the override is not plain JSON, or is NaN or Infinity |
| `DivergenceError` (core) | a replay makes a call that differs from the recording |
| `AgentProtocolError` | stored session metadata is missing or incomplete |

## HTTP routes

The HTTP layer is in `src/revenant_dev/http.py`. Each route calls the function in the table above.
Run it with `python -m revenant_dev.http`. It binds `127.0.0.1:8000` only, and CORS allows
`http://localhost:5173` and `http://127.0.0.1:5173`.

| Method | Path | Calls | Success | Other codes |
|---|---|---|---|---|
| GET | `/sessions` | `list_sessions` | 200 | none |
| GET | `/sessions/{session_id}` | `get_session` | 200 | 404 |
| GET | `/sessions/{session_id}/replay` | `replay_summary` | 200 | 404, 409 |
| GET | `/sessions/{session_id}/bad-edit` | `find_bad_edit` | 200 | 404 |
| POST | `/sessions/{session_id}/fork` | `fork` | 200 | 400, 404, 409, 422 |

The fork body is `{"at_step": int, "override": any JSON value (default null), "use_override":
bool (default false)}`.

### Status codes

| Code | Meaning | Cases | Test |
|---|---|---|---|
| 200 | success | every route | `test_list_sessions_endpoint_equals_the_function`, `test_get_session_endpoint_equals_the_function`, `test_replay_endpoint_equals_the_function`, `test_bad_edit_endpoint_equals_the_function`, `test_fork_endpoint_returns_a_child_with_the_functions_diff` |
| 400 | fork refused | no `use_override`; `at_step` is not a call step; NaN or Infinity override | `test_fork_without_use_override_returns_400_not_500`, `test_fork_at_a_non_call_step_returns_400`, `test_non_finite_override_returns_400_and_creates_no_child` |
| 404 | unknown session | any route | `test_unknown_session_returns_404_on_every_route` |
| 409 | replay diverged from the recording | replay of a session whose first call differs | `test_divergence_maps_to_409_with_step_and_details` |
| 409 | no agent metadata | replay or fork of a session recorded without the agent's metadata | `test_session_without_agent_metadata_maps_to_409_with_message` |
| 422 | bad request body | fork body with a missing or mistyped field | `test_fork_body_without_at_step_returns_422` |
| 500 | any other error (fallback) | none | no test |

### Error bodies

Most errors return `{"detail": "<message>"}`.

A 409 divergence also returns the fields below. This is a shape, not captured output. `step` is the first call that differs. `expected`
is what the recording holds at that step, `actual` is what the replay asked for, and `reason`
names the mismatch, for example `arguments differ` or `different tool name`.

```json
{"detail": "divergence at step 1: arguments differ (...)", "step": 1, "expected": {...}, "actual": {...}, "reason": "arguments differ"}
```

A 422 comes from FastAPI and returns its standard list of field errors, `{"detail": [{"type",
"loc", "msg", "input"}]}`.
