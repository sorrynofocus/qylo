Name: clang and LLVM workflow guide
Description: Task guide for the clang compiler and LLVM tools: compiling and linking, generating LLVM IR (.ll) and bitcode (.bc), optimizing IR with opt, compiling IR with llc, running IR with lli, linking bitcode, assembly output, preprocessing, AST dumps, sanitizers, LTO, cross-compiling and clang-cl on Windows.

Safety: safe

# clang and LLVM workflow guide

## What clang and LLVM are

clang is the C, C++ and Objective-C compiler front end of the LLVM project. clang turns source code
into LLVM IR (intermediate representation), LLVM optimizes the IR, and the LLVM back end turns it
into machine code. The LLVM tools used alongside clang are `opt` (IR optimizer), `llc` (IR to
assembly or object code), `lli` (runs IR directly), `llvm-as` / `llvm-dis` (convert between text IR
and bitcode), `llvm-link` (links bitcode files), `llvm-objdump`, `llvm-nm` and `lld` (the linker).
The full list of clang command-line options is in the clang reference (`clang --help`).
On Windows the executable is `clang.exe`; `clang-cl.exe` is the MSVC-compatible driver.

## clang: compile and link a program

Compile and link a single C file:

    clang hello.c -o hello

Compile a C++ file:

    clang++ main.cpp -o main

On Windows use an `.exe` output name:

    clang hello.c -o hello.exe

Compile several files and link them together:

    clang main.c util.c -o app

## clang: compile only (object files) then link

Compile each file to an object file without linking (`-c`):

    clang -c main.c -o main.o
    clang -c util.c -o util.o

Link the object files:

    clang main.o util.o -o app

## clang: optimization, warnings, debug info and language standard

    clang -O2 -Wall -Wextra -g -std=c17 main.c -o app
    clang++ -O3 -std=c++20 main.cpp -o app

- `-O0` no optimization (default), `-O1`, `-O2`, `-O3`, `-Os` (size), `-Oz` (smallest size).
- `-g` adds debug information.
- `-Wall -Wextra` enable common warnings; `-Werror` turns warnings into errors.
- `-std=c11`, `-std=c17`, `-std=c++17`, `-std=c++20` select the language standard.
- `-I dir` adds an include directory, `-D NAME=value` defines a macro, `-L dir` adds a library
  directory, `-l name` links a library.

## clang: generate LLVM IR (.ll text)

Emit human-readable LLVM IR for a C file:

    clang -S -emit-llvm hello.c -o hello.ll

Emit optimized IR:

    clang -O2 -S -emit-llvm hello.c -o hello.ll

C++ works the same way:

    clang++ -S -emit-llvm -std=c++20 main.cpp -o main.ll

`-S -emit-llvm` writes textual IR (`.ll`). `-c -emit-llvm` writes binary bitcode (`.bc`).

## clang: generate LLVM bitcode (.bc)

    clang -c -emit-llvm hello.c -o hello.bc

Convert bitcode to readable IR with llvm-dis:

    llvm-dis hello.bc -o hello.ll

Convert readable IR back to bitcode with llvm-as:

    llvm-as hello.ll -o hello.bc

## clang: generate IR that opt can optimize later

At `-O0` clang marks every function `optnone`, so `opt` will not optimize it. To produce unoptimized
IR that is still optimizable, disable that attribute:

    clang -O0 -Xclang -disable-O0-optnone -S -emit-llvm hello.c -o hello.ll

## opt: optimize LLVM IR

Run the standard O2 pipeline on an IR file and write text IR:

    opt -passes="default<O2>" hello.ll -S -o hello.opt.ll

Run individual passes, for example promote memory to registers and simplify control flow:

    opt -passes=mem2reg,simplifycfg hello.ll -S -o hello.opt.ll

Verify that an IR file is well formed:

    opt -passes=verify hello.ll -disable-output

## llc: compile LLVM IR to assembly or an object file

IR to target assembly:

    llc hello.ll -o hello.s

IR to an object file:

    llc -filetype=obj hello.ll -o hello.o

With optimization:

    llc -O2 hello.ll -o hello.s

## clang: compile LLVM IR to an executable

clang accepts `.ll` and `.bc` files as input:

    clang hello.ll -o hello

## lli: run LLVM IR directly

Execute IR or bitcode with the LLVM interpreter/JIT (the file needs a `main` function):

    lli hello.ll

## llvm-link: link several IR or bitcode files

    clang -c -emit-llvm main.c -o main.bc
    clang -c -emit-llvm util.c -o util.bc
    llvm-link main.bc util.bc -o app.bc
    llvm-dis app.bc -o app.ll

Then build an executable from the linked bitcode:

    clang app.bc -o app

## clang: full pipeline from C to IR to executable

    clang -O0 -Xclang -disable-O0-optnone -S -emit-llvm hello.c -o hello.ll
    opt -passes="default<O2>" hello.ll -S -o hello.opt.ll
    llc -filetype=obj hello.opt.ll -o hello.o
    clang hello.o -o hello

## clang: assembly output

Emit target assembly instead of an object file:

    clang -S hello.c -o hello.s

Intel syntax on x86:

    clang -S -masm=intel hello.c -o hello.s

## clang: keep all intermediate files

`-save-temps` keeps the preprocessed source (`.i`), bitcode (`.bc`), assembly (`.s`) and object
file (`.o`) in the current directory:

    clang -save-temps hello.c -o hello

## clang: preprocess only

Run only the preprocessor and print the result:

    clang -E hello.c

Write the preprocessed output to a file:

    clang -E hello.c -o hello.i

List the macros that are defined:

    clang -dM -E hello.c

## clang: syntax check and AST dump

Check syntax without producing output:

    clang -fsyntax-only main.c

Dump the clang AST (abstract syntax tree):

    clang -Xclang -ast-dump -fsyntax-only main.c

## clang: show the commands the driver would run

Print, but do not run, the compiler, assembler and linker commands:

    clang -### hello.c -o hello

Print verbose information, including include search paths:

    clang -v hello.c -o hello

## clang: header dependency files for make and ninja

Write a `.d` dependency file while compiling (used by Makefiles and `depfile` in build.ninja):

    clang -MMD -MF main.o.d -c main.c -o main.o

Write a compilation database fragment for one file:

    clang -MJ main.json -c main.c -o main.o

## clang: sanitizers

Build with AddressSanitizer and UndefinedBehaviorSanitizer:

    clang -g -fsanitize=address,undefined main.c -o app

Thread sanitizer (Linux/macOS):

    clang -g -fsanitize=thread main.c -o app

## clang: link time optimization and the lld linker

Full LTO:

    clang -O2 -flto main.c util.c -o app

ThinLTO:

    clang -O2 -flto=thin main.c util.c -o app

Use the LLVM lld linker:

    clang -fuse-ld=lld main.c -o app

With `-flto`, `clang -c` writes LLVM bitcode inside the `.o` file instead of machine code.

## clang: compile time profiling

Write a Chrome trace JSON file showing where compile time was spent:

    clang -ftime-trace -c main.c -o main.o

## clang: cross-compiling with --target

Compile for another target triple:

    clang --target=aarch64-linux-gnu -c main.c -o main.o
    clang --target=x86_64-pc-windows-msvc -c main.c -o main.obj
    clang --target=wasm32 -S -emit-llvm main.c -o main.ll

Print the default target triple and version:

    clang --version

Print the LLVM IR for a target without needing that target's system headers:

    clang --target=riscv64-unknown-elf -S -emit-llvm -ffreestanding main.c -o main.ll

## clang-cl: MSVC-compatible clang on Windows

`clang-cl` accepts cl.exe style options:

    clang-cl /O2 /W4 main.c /Fe:app.exe

Compile only:

    clang-cl /c main.c /Fo:main.obj

Pass clang driver options through clang-cl with `/clang:`, for example to emit LLVM bitcode and
then convert it to readable IR:

    clang-cl /c /clang:-emit-llvm main.c /Fo:main.bc
    llvm-dis main.bc -o main.ll

## LLVM tools: inspect object files and binaries

Disassemble an object file or executable:

    llvm-objdump -d main.o

List symbols:

    llvm-nm main.o

Show section headers:

    llvm-objdump -h main.o

## clang: generate LLVM IR for a whole CMake or Ninja project

Configure the project with clang and export a compilation database:

    cmake -S . -B build -G Ninja -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_EXPORT_COMPILE_COMMANDS=ON

`build/compile_commands.json` lists the exact clang command for every source file. To get IR for one
file, take its command, replace `-c` with `-S -emit-llvm`, and change the `-o` output to a `.ll` file.
`ninja -C build -t commands <target>` prints the same commands. See the build systems guide for a
CMake custom target and a Makefile rule that emit IR as part of the build.
