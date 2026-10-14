# AutoPublisher Privacy Policy

**Effective date:** 2026-10-14

AutoPublisher is an open-source, local, single-user application. You download it and run it
on your own computer to organize, schedule and publish your own images, videos and text
posts to social media accounts that you connect. There is no AutoPublisher service, server,
user account or website that collects your data: the project's only public presence is its
source code repository at <https://github.com/MarcosSM21/autopublisher>.

This policy explains what data the application handles on your computer and what it sends to
third parties when you use it.

## 1. Who is responsible for your data

You are. AutoPublisher runs entirely on your own computer, under your control. The
maintainers of the project do not operate any server for it and **do not receive, collect,
store or have access to** any of your data, content or credentials.

## 2. Data stored on your computer

AutoPublisher stores the following only on your own computer:

- **Your content and settings**: projects, account names and handles you enter, imported
  media files, titles, descriptions, hashtags, schedules and publication history, in a local
  SQLite database and the local file system.
- **Public profile information of connected accounts**, as returned by each platform's
  official API (for example a channel or account ID, username or display name, and profile
  picture URL), plus connection dates and status.
- **Access credentials** (OAuth access tokens and, where the platform issues them, refresh
  tokens) for the accounts you connect. These are stored only in your operating system's
  secure credential store (keyring). They are never written to the database, log files or
  the browser's storage.
- **Application configuration** that you create yourself (for example the client ID/key and
  secret of your own developer apps), in local files that are not part of the source code.

## 3. Data sent to third parties

AutoPublisher only communicates with the official APIs of the services you choose to use,
and only to perform actions you request or schedule:

- **Social media platforms you connect** (YouTube/Google, Instagram/Meta, Threads/Meta and
  TikTok): to authorize the connection, read the basic public profile of the connected
  account, keep the connection valid, and publish the content you choose. Each platform
  processes that data under its own privacy policy.
- **Temporary media storage you configure** (optional, used for platforms that fetch media
  from a URL, such as Instagram and Threads): a temporary private copy of the media being
  published is uploaded to an S3-compatible bucket that you own, shared with the platform
  through a signed, expiring URL, and deleted after publishing.

AutoPublisher does not include analytics, advertising, tracking or telemetry, and does not
sell or share data with anyone else.

## 4. TikTok

If you connect a TikTok account, AutoPublisher requests only these permissions:

- `user.info.basic` — to identify the connected account (its open ID, display name and
  avatar) and confirm the connection is still valid;
- `video.publish` — to publish videos that you choose to your TikTok account.

AutoPublisher uses this data only to show which TikTok account is connected and to publish
content at your request. The TikTok tokens are stored only in your computer's secure
credential store. When you disconnect the account, AutoPublisher asks TikTok to revoke its
access and deletes the stored tokens.

## 5. Retention and deletion

All data stays on your computer until you delete it. You can:

- disconnect any account in AutoPublisher, which deletes its stored credentials (and, for
  TikTok, asks TikTok to revoke the access);
- revoke AutoPublisher's access at any time from each platform's own settings (for example
  TikTok's *Manage app permissions*, Google's third-party access page, or Instagram/Threads
  *Website permissions*);
- delete the application's local data directory and its entries in your secure credential
  store.

## 6. Security

Credentials are kept in the operating system's secure credential store, and the application
is designed so that tokens and secrets never appear in its database, logs or user interface.
Because the application runs on your computer, the security of your data also depends on
the security of that computer.

## 7. Children

AutoPublisher is not directed to children and does not knowingly process children's data.

## 8. Changes

Changes to this policy are published in this file in the project repository, with a new
effective date. The full history is visible in the repository's commit history.

## 9. Contact

Questions about this policy can be asked by opening an issue in the project repository:
<https://github.com/MarcosSM21/autopublisher/issues>.
