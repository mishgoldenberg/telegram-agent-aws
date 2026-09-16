r"""
The phrasing corpus: what people actually send, not what documentation assumes.

Each case is (prompt, expected). expected is one of:

    "tool_name"          exactly that tool must be called
    {"a", "b"}           any one of these is acceptable
    None                 NO tool call - a conversational reply is correct
    ANY                  any tool, or none; only the failure check applies

Every case additionally fails if the user would have seen an error reply
(the backstop, a "couldn't" message, or a raw {"error": ...}), because that is
the thing being hunted: a reply that is useless to a human.

Grouped by intent so a failure points at a feature, not just a line number.
"""

ANY = "__any__"

CASES: list[tuple[str, object]] = [

    # ── calendar: read ────────────────────────────────────────────────────
    ("What's on my calendar today?",                 "list_calendar_events"),
    ("what do i have today",                         "list_calendar_events"),
    ("whats my schedule for the next week",          "list_calendar_events"),
    ("ayo what do i got going on tomorrow",          "list_calendar_events"),
    ("am I free on Friday?",                         "list_calendar_events"),
    ("anything planned this weekend",                "list_calendar_events"),
    ("do i have meetings next week?",                "list_calendar_events"),
    ("show me my agenda",                            "list_calendar_events"),
    ("what's coming up",                             "list_calendar_events"),
    ("busy tomorrow?",                               "list_calendar_events"),
    ("06.09-12.09",                                  "list_calendar_events"),
    ("что у меня на следующей неделе",               "list_calendar_events"),
    ("покажи расписание на сегодня",                 "list_calendar_events"),
    ("whats on the calender tommorow",               "list_calendar_events"),  # typos
    ("my calendar",                                  "list_calendar_events"),

    # ── calendar: write ───────────────────────────────────────────────────
    ("add gym to my calendar tomorrow at 8pm",       "create_calendar_event"),
    ("put dentist on friday 14:00",                  "create_calendar_event"),
    ("schedule a call with mom sunday 19:00",        "create_calendar_event"),
    ("создай событие завтра в 10 утра тренировка",   "create_calendar_event"),
    ("book me 2 hours of study tomorrow at 9",       "create_calendar_event"),

    # ── tasks: read ───────────────────────────────────────────────────────
    ("What tasks do I have?",                        "list_tasks"),
    ("show me my tasks",                             "list_tasks"),
    ("what's on my todo list",                       "list_tasks"),
    ("whats left to do today",                       {"list_tasks", "list_calendar_events"}),
    ("покажи мои задачи",                            "list_tasks"),
    ("my to-do",                                     "list_tasks"),

    # ── tasks: write ──────────────────────────────────────────────────────
    ("add task to call the dentist tomorrow",        "create_task"),
    ("remind me to buy milk",                        {"create_task", "set_reminder"}),
    ("add study to my tasks for tomorrow",           "create_task"),
    ("new task: renew passport",                     "create_task"),
    ("добавь задачу купить хлеб",                    "create_task"),
    ("mark buy milk as done",                        "complete_task"),

    # ── weather ───────────────────────────────────────────────────────────
    ("What's the weather today?",                    "get_weather"),
    ("weather",                                      "get_weather"),
    ("ayo, what's the weather for tomorrow in Tirat Hacarmel", "get_weather"),
    ("hows the weather in Haifa",                    "get_weather"),
    ("is it going to rain tomorrow",                 "get_weather"),
    ("do i need an umbrella",                        "get_weather"),
    ("какая погода сегодня",                         "get_weather"),
    ("погода завтра в Хайфе",                        "get_weather"),
    ("weather in טירת כרמל",                         "get_weather"),
    ("how hot is it outside",                        "get_weather"),
    ("whats the temp tmrw",                          "get_weather"),

    # ── email ─────────────────────────────────────────────────────────────
    ("summarise my unread emails",                   "summarize_unread"),
    ("any new mail?",                                "summarize_unread"),
    ("check my inbox",                               "summarize_unread"),
    ("did i get anything important today",           {"summarize_unread", "search_email"}),
    ("find emails from gitlab",                      "search_email"),
    ("что там в почте",                              "summarize_unread"),

    # ── reminders ─────────────────────────────────────────────────────────
    ("remind me in 2 hours to take the laundry out", "set_reminder"),
    ("remind me tomorrow at 9 to call the bank",     {"set_reminder", "create_task"}),

    # ── memory ────────────────────────────────────────────────────────────
    ("remember that my wifi password hint is the dog's name", "save_memory"),
    ("remember I prefer morning workouts",           "save_memory"),

    # ── search ────────────────────────────────────────────────────────────
    ("who won the world cup in 2022",                "web_search"),
    ("what's the capital of Portugal",               ANY),

    # ── logging ───────────────────────────────────────────────────────────
    ("log 500 calories for lunch",                   "log_calories"),
    ("i went to the gym today",                      {"log_habit", "log_calories"}),
    ("show my log for today",                        "get_log"),

    # ── conversational: MUST NOT call a tool ──────────────────────────────
    ("hello",                                        None),
    ("hi there",                                     None),
    ("thanks!",                                      None),
    ("who are you?",                                 None),
    ("привет",                                       None),
    ("ok",                                           None),
    ("what can you do?",                             None),

    # ── awkward but must not error ────────────────────────────────────────
    ("👍",                                            ANY),
    ("asdfghjkl",                                    ANY),
    ("?",                                            ANY),
    ("weather and my calendar for tomorrow",         {"get_weather", "list_calendar_events"}),
    ("add gym tomorrow and tell me the weather",     {"create_calendar_event", "get_weather", "create_task"}),
    ("what did i do last week",                      ANY),
    ("cancel",                                       ANY),
]

# Slash commands, checked without the model - instant.
COMMAND_CASES: list[tuple[str, str]] = [
    ("/help",       "Assistant"),
    ("/start",      "Assistant"),
    ("/menu",       "Assistant"),
    ("/weather",    "Weather"),
    ("/reminders",  "reminder"),
    ("/memory",     ""),
    ("/log",        ""),
    ("/task",       "Step 1/5"),
    ("/event",      "Step 1/5"),
    ("/template",   "not available"),
    ("/done",       "not available"),
    ("/nonsense",   "Unknown command"),
    ("/cancel",     "Nothing to cancel"),
]
