Name: Build systems guide (CMake and Make)
Description: How to generate and run a build system for C and C++ source code with CMake and GNU Make: writing CMakeLists.txt and Makefiles, choosing Ninja or Makefile generators, using clang, building, installing, testing, cleaning, and adding targets that emit LLVM IR.

Safety: safe

# Build systems guide: CMake and Make

## What a build system generator is

CMake is a build system generator: it reads `CMakeLists.txt` and writes a native build system,
such as `build.ninja` for Ninja, `Makefile` for GNU Make or NMake, or a Visual Studio solution.
GNU Make (`make`) reads a `Makefile` directly. Ninja is covered in the Ninja guide, and clang and
LLVM IR in the clang and LLVM workflow guide.

## CMake: minimal CMakeLists.txt for a C or C++ project

Put this `CMakeLists.txt` in the project root, next to a `src` folder:

    cmake_minimum_required(VERSION 3.20)
    project(app LANGUAGES C CXX)

    set(CMAKE_C_STANDARD 17)
    set(CMAKE_CXX_STANDARD 20)
    set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

    add_executable(app src/main.c src/util.c)
    target_include_directories(app PRIVATE include)
    target_compile_options(app PRIVATE -Wall -Wextra)

Add a library and link it:

    add_library(util STATIC src/util.c)
    target_link_libraries(app PRIVATE util)

## CMake: generate a build system for existing source code

Configure the source directory `.` into the build directory `build`:

    cmake -S . -B build

Choose the generator with `-G`:

    cmake -S . -B build -G Ninja
    cmake -S . -B build -G "Unix Makefiles"
    cmake -S . -B build -G "Ninja Multi-Config"
    cmake -S . -B build -G "NMake Makefiles"
    cmake -S . -B build -G "MinGW Makefiles"
    cmake -S . -B build -G "Visual Studio 17 2022"

List all generators available on this machine:

    cmake --help

## CMake: generate a Ninja build that uses clang

    cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_EXPORT_COMPILE_COMMANDS=ON

Then build with Ninja:

    ninja -C build

`CMAKE_BUILD_TYPE` is `Debug`, `Release`, `RelWithDebInfo` or `MinSizeRel`. The compiler can only
be chosen on the first configure; use a new build directory or `cmake --fresh` to change it.

## CMake: build, rebuild and build one target

    cmake --build build
    cmake --build build -j 8
    cmake --build build --target app
    cmake --build build --config Release
    cmake --build build --clean-first
    cmake --build build --verbose

`--config` is needed for multi-config generators (Visual Studio, Ninja Multi-Config).

## CMake: clean, reconfigure, install and test

Clean build outputs:

    cmake --build build --target clean

Reconfigure from scratch, discarding the cache (CMake 3.24 or newer):

    cmake --fresh -S . -B build

Install into a prefix:

    cmake --install build --prefix ./install

Run tests registered with `enable_testing()` and `add_test()`:

    ctest --test-dir build --output-on-failure

List cache variables and their values:

    cmake -L -N build

## CMake: add a target that emits LLVM IR with clang

Add a custom target to `CMakeLists.txt` that writes LLVM IR for `src/main.c` into the build folder.
It requires clang as the C compiler:

    add_custom_command(
      OUTPUT ${CMAKE_BINARY_DIR}/main.ll
      COMMAND ${CMAKE_C_COMPILER} -S -emit-llvm -O1 -I${CMAKE_SOURCE_DIR}/include
              ${CMAKE_SOURCE_DIR}/src/main.c -o ${CMAKE_BINARY_DIR}/main.ll
      DEPENDS ${CMAKE_SOURCE_DIR}/src/main.c
      COMMENT "Emitting LLVM IR for main.c")
    add_custom_target(emit-ir DEPENDS ${CMAKE_BINARY_DIR}/main.ll)

Build only the IR:

    cmake --build build --target emit-ir

or with Ninja:

    ninja -C build emit-ir

## CMake: end-to-end example, source to build system to LLVM IR

    cmake -S . -B build -G Ninja -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
    ninja -C build
    clang -S -emit-llvm -Iinclude src/main.c -o build/main.ll

`build/compile_commands.json` holds the exact flags CMake used for each file; reuse them when
emitting IR so the IR matches the real build.

## Make: minimal Makefile for clang

Recipe lines in a Makefile must start with a TAB character, not spaces.

    CC      = clang
    CFLAGS  = -O2 -Wall -Wextra -Iinclude
    SRCS    = src/main.c src/util.c
    OBJS    = $(SRCS:.c=.o)
    IRS     = $(SRCS:.c=.ll)

    .PHONY: all clean ir

    all: app

    app: $(OBJS)
    	$(CC) $(OBJS) -o $@

    %.o: %.c
    	$(CC) $(CFLAGS) -MMD -MP -c $< -o $@

    %.ll: %.c
    	$(CC) $(CFLAGS) -S -emit-llvm $< -o $@

    ir: $(IRS)

    clean:
    	rm -f $(OBJS) $(IRS) $(OBJS:.o=.d) app

    -include $(OBJS:.o=.d)

- `$@` is the target, `$<` is the first prerequisite, `$^` is all prerequisites.
- `-MMD -MP` makes clang write `.d` header dependency files that `-include` reads back.
- `.PHONY` marks targets that are not files.

## Make: run a build

    make
    make ir
    make clean
    make -j 8
    make -C src
    make -f other.mk
    make CC=clang CFLAGS="-O0 -g"

- `-j N` runs N jobs in parallel.
- `-n` is a dry run: print commands without running them.
- `-B` rebuilds everything unconditionally.
- `-C dir` changes to `dir` first; `-f file` uses a different makefile.
- `VAR=value` on the command line overrides a variable.

## Make on Windows

GNU Make is not included with Windows. It is available as `mingw32-make` (MSYS2/MinGW) or
`make` from MSYS2, Git Bash or Chocolatey. Visual Studio provides `nmake`, which uses a different
Makefile syntax; generate NMake files with `cmake -G "NMake Makefiles"` and build with:

    nmake

`rm -f` in a Makefile needs a POSIX shell; under cmd.exe use `del /q` instead.

## Choosing Ninja or Make

Ninja is faster for incremental builds and is the usual choice with CMake and clang
(`cmake -G Ninja`). Make is available on most Unix systems and is easier to write by hand. Both can
emit LLVM IR through clang with `-S -emit-llvm`.
