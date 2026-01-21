---
title:          Beta Test Plan Example
subtitle:       Microsoft Teams example
author:         Lisa Nay
module:         G-EIP-700
version:        1.0
---

<!--# **BETA TEST PLAN – Microsoft Teams example**-->

## **1. Project context**
Microsoft Teams is an online collaboration app that centralizes professional communication (messages, meetings, and files) in a single workspace to facilitate teamwork. It works with teams and thematic channels where users can chat, share and co-edit Office files, and organize audio/video meetings all within the same interface.

## **2. User Roles**
The following roles will be involved in beta testing.

| **Role Name**  | **Description** |
|--------|----------------------|
| Admin        | An administrator manage organisation settings, create and delete teams, assign roles, and control access to resources|
| Employee     | A regular user who can participate in conversations, join teams, send messages, share files, and participate in video calls |

---

## **3. Feature table**
All of the listed features will be demonstrated during the beta presentation

| **Feature ID** | **User role** | **Feature name** | **Short description** |
|--------------|---------------|-------------------------|--------------------------------------|
| F1 | Everyone | Login | A user can log in with an existing account |
| F2 | Admin | Create a new team | Create a new team with a name |
| F3 | Everyone | Add members to a team | Add new members to an existing team |
| F4 | Everyone | Remove members | Remove a member from a team |
| F5 | Everyone | Create a new channel | Create a new channel in a team |
| F6 | Everyone | Rename a channel | Renaming an existing channel in a team |
| F7 | Everyone | Delete a channel | Delete a channel from a team |
| F8 | Everyone | Send a message | Send a text message in a channel or conversation |
| F9 | Everyone | Receive a message | See messages sent by others in near real time |
| F10 | Everyone | Delete a message | Delete one of your own messages |
| F11 | Everyone | Mention someone | Mention a user with a targeted notification |
| F12 | Everyone | Attach a file | Attach a file to a message in a channel |
| F13 | Everyone | Start a video call | Starting a video call from a channel or conversation |
| F14 | Everyone | Join a video call | Join an ongoing video call |
| F15 | Everyone | Mute/unmute audio | Mute and unmute your microphone during a call |
| F16 | Everyone | Turn on/off video | Enable/disable video during a call |
| F17 | Everyone | Leave call | Exit a video call properly |
| F18 | Everyone | Access settings | Access a page with basic account settings |

---

## **4. Success criteria**

| **Feature ID** | **Key success criteria** | **Indicator/metric** | **Result** |
|--------------|---------------------------------------|-----------------------|----------------|
| F1 | A user logs in with their email address and password without any errors | 20 attempts, 0 failures related to the application | Achieved (20/20)|
| F2 | Creation of a team visible in the list of teams | 5 teams created, all visible | Achieved |
| F3 | Adding members immediately makes the team accessible to newcomers | 10 additions, all functional| Achieved |
| F4 | UA removed member no longer has access to the team's channels | 5 withdrawals, 1 residual access bug| Partially achieved |
| F5 | Creating a channel makes the channel visible to all members | 5 channels created, all visible | Achieved|
| F6 | Renaming a channel updates the name for all members | 5 renames, consistent across all clients | Achieved |
| F7 | Deleting a channel removes it from the list and blocks access | 3 deletions, 0 phantom channels | Achieved |
| F8 | A text message is sent and appears in the channel | 50 messages sent, 0 lost | Achieved (50/50) |
| F9 | Received messages appear in less than 2 seconds | Average latency < 2 seconds over 30 tests | Partially (2.3 s) |
| F10 | The user can delete one of their messages and it will disappear from the channel | 10 deletions, all effective and persistent | Achieved (10/10) |
| F11 | The mentioned user receives a visible notification | 20 mentions, 20 visible notifications| Achieved |
| F12 | An attached file is uploaded and can be downloaded by other members | 15 files tested, 1 failure | Partially achieved |
| F13 | Starting a video call connects at least two participants without crashing | 10 calls, 1 crash | Partially achieved |
| F14 | Joining an ongoing call takes less than 10 seconds | 15 attempts, 14 successes | Partially achieved |
| F15 | Mute/unmute effectively changes the audio status for other participants | 20 switches, all taken into account | Achieved |
| F16 | Enabling/disabling video updates the display for everyone | 20 switches, 2 significant latencies | Partially achieved |
| F17 | Leaving the call properly ends the local session | 15 outings, 0 zombie sessions | Achieved |
| F18 | Accessing the settings allows you to change at least one setting (language, etc.) | 10 changes, all saved | Achieved |

