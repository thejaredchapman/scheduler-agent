# The Front Desk scheduler: a guide for business users

This guide is for managers, office leads, executive assistants and anyone else who wants to know what this scheduling assistant does, how to try it, and where its limits are. You do not need to know how to program to read it.

> **In one minute**
>
> - You type a meeting request in plain words. An AI assistant looks at the calendars of a made-up company, picks a time and a room, and shows you a proposal.
> - The assistant cannot send anything. A person has to press "Approve and send", and ordinary software does the sending.
> - The time, each person's local time, the room and the attendees are worked out by code, not by the AI. The AI's own explanation is shown separately as "Claude's note".
> - It is a demonstration with fake people and fake calendars. Nothing has been put on the internet yet.

## What this is

The Front Desk is an AI assistant that does one job: it finds a meeting time. You write a request such as "Find 45 minutes next week for Priya, Tom and Mei, plus a meeting room. Mornings only, New York time." The assistant looks up who those people are, searches their calendars, picks a slot, pencils in a room and shows you what it found.

What you see is split into two kinds of information, and the page keeps them apart.

**Worked out by code.** The start time, the end time, each attendee's local time, the room and the list of attendees. Software checks that everyone is free and at work and that the room is big enough. The AI is told to use the software for all calendar and time-zone arithmetic, and the page shows only the software's numbers for these.

**Claude's note.** A short summary, the reasons the slot is a good choice, and any trade-offs (for example "this is not a morning, as you asked"). This is Claude's own wording. It is useful, but software does not check it, and it can mention a time that is not checked.

The demo company, Acme Corp, is fictional. It has eight people in four places (New York, London, Denver and Singapore), four meeting rooms in the New York office, and one week of busy calendars. "Today" in the demo is fixed at Tuesday 20 October 2026, so "next week" always means 26 to 30 October 2026.

## What it could do for your team

These points come from features the demo really has. Where something was not measured, this section says so.

**A person stays in charge.** The assistant has no tool for sending. It can only look things up, pencil in a hold, and hand you a proposal or a question. Sending happens only after a person approves, and it can be undone for 10 minutes.

**Time zones handled by software.** In the tests, requests that crossed London, New York, Denver and Singapore were the cases most likely to go wrong. Because the arithmetic is done by code, the times shown to each attendee come from the same calculation every time.

**Honest "this cannot be done" answers.** If a request cannot be met, for example a meeting that has to fit working hours in both Singapore and New York with no overlap, the assistant is told to ask you a short question instead of forcing a bad slot. In our test it asked a question every time one was needed.

**Preview before sending.** A "Dry run" shows the invites that would go out and whether everyone is still free, and sends nothing.

**Speed.** In our test a typical request took about 6.5 seconds. Speed varies with how busy the AI service is.

**What was not measured.** We did not measure time or money saved, and we did not test with real users or real calendars.

## How to try the demo

Someone technical has to start the demo on a computer, using the steps in the developer guide. It then opens as a web page.

1. Pick one of the four sample requests, or type your own (up to 500 characters).
2. Press "Find a time" and watch the steps appear in the desk log as the assistant works.
3. Read the proposal. The times and the room are at the top; Claude's note is labelled.
4. Press "Dry run" to preview, "Reject" to throw it away, or "Approve and send" to put it in the outbox.
5. Within 10 minutes you can undo a send from the outbox.
6. If the assistant asks a question instead, type your answer and send it.

The four samples are: a simple meeting, London and New York (the four-hour overlap in the working week), four people in two regions where only one slot fits, and an impossible request that makes the assistant ask a question.

Nothing is really sent. The "outbox" is a list on the page, kept in memory for your visit and forgotten after about 30 minutes of inactivity.

If the day's allowance of AI use has run out, the page replays recorded runs of the four samples instead, and it says so.

## Use cases

The demo uses a made-up company so that anyone can check the results. The same pattern fits other settings, if the calendars are connected and the assistant is re-tested.

- **Cross-region team meetings.** Find a slot that respects everyone's working hours in several time zones.
- **Room booking.** Match group size and equipment (screen, video, whiteboard) to a room.
- **Executive assistant support.** Draft a proposal for a person to approve instead of booking directly.
- **Asking the right question.** Notice that a request is missing the length or names someone who does not exist, and ask.

Each of these would need its own test requests, and a real calendar connection that this demo does not have.

## What it is not

- **Not connected to real calendars.** It reads fixed, made-up data. It cannot see your calendar and nothing it "sends" goes anywhere.
- **Not checked end to end.** Code checks the slot, the local times, the room and the attendees. It does not check the sentences in Claude's note.
- **Not a measured product.** The test was small, and we wrote the test requests ourselves (see below).
- **Not deployed.** Nothing has been put on the internet. There is no hosting, no accounts and no stored requests.
- **Not able to send on its own.** "Sent without approval: 0" is true by design, because the AI has no sending tool, and tests check it. It is not a result the AI earned.
- **Not guaranteed free of the earlier problem.** See the next section about the leaked-markup check that has not been measured.

## How well it worked in testing

We wrote 16 scheduling requests and ran each one three times, one at a time, for 48 runs. They fall into four groups: simple requests, time-zone requests, tight requests where few slots fit, and impossible or unclear requests. This is a development set of 16 requests written by us, not an independent test. The full results are in `eval/results.md` and `eval/results-first-run.md`, and the story of what went wrong is in `eval/NOTES.md`.

**The first run: 79% success.** Ten of the 48 runs ended with the assistant unable to produce a valid proposal. We first guessed that the AI was leaving out its reasons. That was wrong. Looking at the recorded calls, in 25 submissions Claude did write its reasons, but it put them inside the summary text as tag-like markup instead of in the separate reasons field. Software saw an empty reasons field and rejected the proposal, and most retries failed the same way. (Another 12 calls with no reasons were questions sent through the old combined form, which never needed reasons.)

**The fix we made, with your approval.** We split the single final step into two: one tool for submitting a proposal and one for asking a question. We then ran the same 48 runs again.

**The re-run: 98% success.** Forty-seven of 48 runs were right. The one miss was a time-zone request that ended as "unable" after the same markup problem. The leaked-markup problem did not disappear: it happened in 3 of the 38 proposal submissions, down from 25 of 63. We do not know why the AI sometimes does it.

**Bad proposals: 0%.** No proposal in either run double-booked anyone, broke working hours or missed a hard requirement. This is because code checks every proposal before it is shown, so a bad one is rejected rather than shown.

**Questions when needed: 100%.** Every time the request was impossible or unclear, the assistant asked a question.

**Sent without approval: 0.** By design, as described above.

**Speed: a median of 6.5 seconds per request**, with about 3.8 model calls per run on average. The slowest run took 13.6 seconds.

**One check that has not been measured.** After both runs we added a check that rejects any summary, reason or trade-off containing leaked markup, with a message telling the AI to send reasons as their own field. Neither measured run includes that check, so we do not know how much it helps. A new run would be needed.

**Limits of all this.** Sixteen requests is small, and we wrote them while building. The groups are of 12 runs each, so one run moves a group's score by about 8 points. Results could differ with other requests, real calendars or a newer model. For the technical details, see the [developer guide](developer-guide.md).

## Frequently asked questions

**Can it double-book someone?** The software checks every proposal, and again when you approve. In testing no bad proposal got through. This is a development result, not a guarantee.

**Does it make things up?** The times and the room come from code. Claude's note is the AI's own wording and is not checked, so read it as a helpful explanation, not as a verified statement.

**Can it send invites by itself?** No. It has no sending tool. A person must press Approve.

**Can it use my calendar?** Not as built. The people, rooms and calendars are fixed demo data. Connecting real calendars would be a separate project and would need new tests.

**Why did it say it was unable to help?** Something went wrong: the AI service failed, it ran out of steps, or it could not produce a proposal that passed the checks. It then gives a reason and no proposal.

**Are my requests stored?** The demo does not save them. The AI service receives them, so do not type anything private.

**Does it cost money?** Each request uses AI service tokens. Prices change, so check the current price. The server also has a daily limit that switches to recorded replays.

**Who do I ask for help?** See the Getting help section of the developer guide.

## Glossary

**Agent.** An AI that decides its own next step, here which calendar to look at or which slot to try, instead of following a fixed script.

**Claude's note.** The summary, reasons and trade-offs in Claude's own words. Not checked by software.

**Hold.** A slot and room pencilled in for a short time, not sent to anyone.

**Proposal.** The result you are asked to approve: a slot, a room, attendees and Claude's note.

**Outbox.** The list of meetings approved in your visit. Each can be undone for 10 minutes.

**Dry run.** A preview of the invites and a check that everyone is still free. Nothing is sent.

**Bad proposal.** One that would double-book someone, break working hours or miss a hard requirement.

**Replay.** A recorded run shown when live answers are paused.

**Token.** A small piece of text. AI services charge by the token.

**Development set.** The 16 requests we wrote while building, as opposed to a fresh test.
