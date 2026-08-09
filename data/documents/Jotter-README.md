![jotter-logo][jotter-logo]

A quick note taking application for those who store useful data. As I chuckle writing this, I suppose the logline can be: _Jot it down, never forget_. 

I **really** liked Microsoft's modern [Sticky Notes][sticky_notes_url] implementation. This is a curt nod keeping a similar look and feel to this development. 

Jotter is an application *currently under development*.  I am learning WPF (very challenging compared to WinForms development) and the work hasn't reached alpha yet. Stay tuned.

---

The concept:

- Clean look
- Very easy to use
- Easy to use back-end database or user friendly data.
- Notes can be managed by a main window (note manager).
- Notes placement on the screen is remembered and multiple notes can be opened at the same time.
- Ability to _export_ the notes to markdown. 
- A settings area to customize the application and its functionality.
- Notes can be opened in separate windows (future settings may include sticky notes where notes can be _pinned_ as opened)


---


_Screen exhibit of the main Jotter window showing the note manager and multiple notes opened for editing_

![jotter-screen001][jotter-screen001]


Jotter, a brief look:

- A standard _dark_ look with larger than life buttons.
- The main window (note manager at the left-most of the exhibit) contains a listing of the notes. I kept a _sticky notes_ look on each of the notes (yellow). Therer are _theme skins_ you can apply! There are _three_ themes currently available to switch between with more on the way!
- On the main window,  _right-clicking_ will produce a context menu that allows you to open the note or delete it. 
- Double-clicking the note (center and right-most of the exhibit), opens a window to edit the note and title.
- Many notes can be brought up to examine or update in their own separate window.
- You can change the title of the notes in the note manager.
- You can import images into notes to visually enhance them.
- You can customize settings to adjust date/time stamp of the notes, logging, and other application behaviors.
- **NO** cloud migrations, syncing in this development. 
- Notes are stored in XML format under the %LOCALAPPDATA%\Jotter location.

<BR>

_Recording of theme switching in Jotter_

![jotter-theme-recording][jotter-theme-recording]

_Screen exhibit to the Jotter application_

![jotter-alpha-exhibit][jotter-alpha-exhibit-hr6uf]


_Screen exhibit showing another view of the Jotter application with image gallery opened within a note_

![jotter-screen002][jotter-screen002]

_Screen exhibit of the settings manager_

![jotter-screen003][jotter-screen003]


---

## Documentation

There's documentation of tracking the project to get familiar with it, lessons learned, failures, and successes. Docs in root will eventually be moved towards a `docs` folder (I've relied heavily into AI assistance recently) . All docs are now AI generated; the brain moves faster than fingers. 

Here comes the roadmap below:

AGENT.MD (soon!) \
When I started using AI assisted development, I was using a single agent to help development. I'll add one soon.

[NOTES MD][jotter-nobuilds-readme] \
**THIS** file gives a life cycle of the project: design, technical development, lessons learned, and more. It's basically a brain dump of my experiences building Jotter. *This* is the place to be where my thoughts and experiences are documented.

#### The documents below are 100% AI generated.:

   [ARCHITECTURE][architecture] \
   This documentation describes the runtime structure of the application. 

   [CODEINTELLIGENCEMAP][codeintelligencemap] \
   This document is a code navigation map explaining file relationships.

   [CODINGTASKS][codingtasks] \
   This document tracks current implementation and what to do next. 

   [DEVONBOARDING][devonboarding] \
   Instead of reverse engineering the codebase, this document can help with onboarding. 

   [REPOMAP][repomap] \
   This document is a map of the repo structure. 



---
## Build Jotter
To build Jotter from source, ensure you have the following prerequisites installed:

- [Visual Studio 2022](https://visualstudio.microsoft.com/) with the **.NET desktop development** workload.
- [.NET 6 SDK](https://dotnet.microsoft.com/en-us/download/dotnet/6.0) or later.

Once the prerequisites are installed:

Clone the repository:
   ```bash
   git clone https://github.com/sorrynofocus/Jotter.git
   cd Jotter
   ```

`auto-build.cmd` will build everything- dedbug and release and packages for publishing.

To quickly build the project without opening Visual Studio 2022 and output build will be placed in the default `bin` and `obj` folders under each project directory, enter:
   ```bash
   dotnet build Jotter.sln
   ```

---



[jotter-nobuilds-readme]:NoBuild\Notes.md
[architecture]:ARCHITECTURE.MD
[codeintelligencemap]:CODEINTELLIGENCEMAP.MD
[codingtasks]:CODINGTASKS.MD
[devonboarding]:DEVONBOARDING.MD
[repomap]:REPOMAP.MD

[sticky_notes_url]: https://apps.microsoft.com/detail/9nblggh4qghw

[jotter-alpha-exhibit-hr6uf]: ./NoBuild/img/Jotter-alpha-screenshot.png

[jotter-logo]: ./build/Icos/jotter-logo.png

[jotter-screen001]: ./NoBuild/img/Jotter-screen-001.png

[jotter-screen002]: ./NoBuild/img/Jotter-screen-002.png

[jotter-screen003]: ./NoBuild/img/Jotter-screen-003.png

[jotter-theme-recording]: ./NoBuild/img/Jotter-theme-Recording.gif
