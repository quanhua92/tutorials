// deployment_linking.cpp — Phase 8 bundle.
//
// GOAL (one line): document and assert the static facts of C++ DEPLOYMENT —
// STATIC vs DYNAMIC linking, the ABI (name mangling / struct layout / vtable),
// libstdc++ vs libc++ (NOT cross-compatible), the Itanium C++ ABI, and
// RPATH/RUNPATH — the deployment pain that Go (single static binary) and Rust
// (musl static) largely avoid.
//
// This is the GROUND TRUTH for DEPLOYMENT_LINKING.md. Every value below is
// either COMPUTED by this file (the typeid() mangled names, the struct/vtable
// sizes, the detected stdlib implementation) or ASSERTED as a standard-fixed
// static fact (the static-vs-dynamic tradeoff table, libstdc++!=libc++, RPATH
// semantics) that the reader verifies externally. Never hand-compute.
//
// Run:
//     just run deployment_linking   (== c++ -std=c++23 -O2 -Wall -Wextra
//                                     -Wpedantic deployment_linking.cpp
//                                     -o /tmp/cpp_deployment_linking
//                                     && /tmp/cpp_deployment_linking)

#include <cstdio>     // printf / fprintf
#include <cstdlib>    // EXIT_FAILURE / exit
#include <cstring>    // memset (banner bar) + strcmp
#include <typeinfo>   // typeid(T).name() — the Itanium ABI mangled name

// Detect which C++ stdlib implementation is in use. This is a REAL computed
// fact: on this Apple-clang box libc++ is active (_LIBCPP_VERSION defined);
// on GCC/Linux libstdc++ is active (__GLIBCXX__ defined). The two are NOT
// ABI-compatible (Section B).
#if defined(_LIBCPP_VERSION)
    #define STDLIB_NAME    "libc++ (clang/LLVM; Apple default)"
    #define STDLIB_VERSION _LIBCPP_VERSION
#elif defined(__GLIBCXX__)
    #define STDLIB_NAME    "libstdc++ (GCC; Linux default)"
    #define STDLIB_VERSION __GLIBCXX__
#else
    #define STDLIB_NAME    "unknown stdlib"
    #define STDLIB_VERSION 0
#endif

// A struct + a polymorphic class used to demonstrate ABI layout and the vtable
// pointer. Defined at GLOBAL scope (external linkage) so the Itanium mangled
// names are the clean textbook form (N5audio9ProcessorE) rather than carrying
// the anonymous-namespace _GLOBAL__N_ prefix. Their sizes/alignments are ABI.
namespace audio {
    struct Processor {          // POD: no virtuals, no vptr
        int sample_rate;
        double gain;
    };
    class Engine {              // has a virtual function -> carries a vptr
    public:
        virtual ~Engine() = default;
        virtual int process(int x) { return x * 2; }
        int channels{2};
    };
}  // namespace audio

namespace {

constexpr int BANNER_WIDTH = 70;

// sectionBanner prints a clearly delimited section divider (the house style).
void sectionBanner(const char* title) {
    char bar[BANNER_WIDTH + 1];
    std::memset(bar, '=', BANNER_WIDTH);
    bar[BANNER_WIDTH] = '\0';
    std::printf("\n%s\nSECTION %s\n%s\n", bar, title, bar);
}

// check asserts an invariant and prints a uniform "[check] ... OK" line.
// On failure it prints to stderr and exits non-zero so `just check`/`just sweep`
// catch it (and ASan/UBSan stay happy — no throw across the verified path).
void check(const char* description, bool ok) {
    if (!ok) {
        std::fprintf(stderr, "INVARIANT VIOLATED: %s\n", description);
        std::exit(EXIT_FAILURE);
    }
    std::printf("[check] %s: OK\n", description);
}

// === Section A — STATIC vs DYNAMIC linking (the tradeoff table) ==============
//
// THE foundational deployment decision in C++. The library's machine code is
// either COPIED INTO your executable (static) or LEFT IN A SEPARATE FILE loaded
// at runtime (dynamic). Every property below follows from that one fork.
void sectionA() {
    sectionBanner("A — STATIC vs DYNAMIC linking (the tradeoff)");

    std::printf("property                | STATIC (.a / libfoo.a)        | DYNAMIC (.so/.dylib/.dll)\n");
    std::printf("------------------------|-------------------------------|--------------------------\n");
    std::printf("library code            | COPIED INTO the executable    | loaded at RUNTIME\n");
    std::printf("executable size         | LARGE (the lib code is inside)| SMALL (the lib is external)\n");
    std::printf("runtime dependency      | NONE (self-contained binary)  | .so/.dylib/.dll MUST exist\n");
    std::printf("ABI compatibility at    | LINK time (resolved once)     | RUNTIME (must match the .so)\n");
    std::printf("shared across processes | NO (each exe has its own copy)| YES (one .so mapped in RAM)\n");
    std::printf("library update          | must RE-LINK the executable   | swap the .so (no re-link)\n");
    std::printf("startup cost            | none (symbols already bound)  | loader resolves the symbols\n");
    std::printf("Linux/Unix file ext     | libfoo.a                      | libfoo.so\n");
    std::printf("macOS       file ext    | libfoo.a                      | libfoo.dylib\n");
    std::printf("Windows      file ext   | foo.lib                       | foo.dll\n");

    // Static facts (standard-fixed definitions of the linking model; asserted,
    // not computed in-TU because modeling them needs multi-file linking).
    check("STATIC: library code is COPIED INTO the executable (self-contained)", true);
    check("STATIC: NO runtime dependency on the .a/.lib", true);
    check("STATIC: must RE-LINK the executable when the library updates", true);
    check("STATIC: executable is LARGER (the library's code lives inside it)", true);
    check("DYNAMIC: the .so/.dylib/.dll is loaded at RUNTIME", true);
    check("DYNAMIC: executable is SMALLER, but the .so MUST be present at runtime", true);
    check("DYNAMIC: the .so MUST be ABI-compatible with the executable at runtime", true);
    check("DYNAMIC: one .so/.dylib is shared across processes (mapped once in RAM)", true);
}

// === Section B — The ABI: name mangling / struct layout / vtable =============
//
// The ABI (Application Binary Interface) is the BINARY-LEVEL contract: how
// types are encoded into symbols (mangling), how structs are laid out
// (padding/offsets), how virtual dispatch works (vtable), and how exceptions
// unwind. A library built with compiler A / stdlib X may NOT link or run with
// compiler B / stdlib Y — the ABI-compatibility problem.
void sectionB() {
    sectionBanner("B — The ABI: name mangling, struct layout, vtable");

    // (1) NAME MANGLING: the compiler encodes each function's signature into a
    // unique symbol so overloads/distinct signatures get distinct link names.
    // typeid().name() exposes the mangled name of a TYPE (Itanium ABI here).
    std::printf("(1) NAME MANGLING (Itanium ABI; typeid(T).name() on this platform):\n");
    std::printf("    typeid(int).name()                = \"%s\"\n", typeid(int).name());
    std::printf("    typeid(double).name()             = \"%s\"\n", typeid(double).name());
    std::printf("    typeid(audio::Processor).name()   = \"%s\"\n", typeid(audio::Processor).name());
    std::printf("    typeid(audio::Engine).name()      = \"%s\"\n", typeid(audio::Engine).name());
    std::printf("    (N...E = nested name; digit-prefix = length of the identifier)\n");

    check("mangled name of int is \"i\" (Itanium builtin encoding)",
          std::strcmp(typeid(int).name(), "i") == 0);
    check("mangled name of double is \"d\" (Itanium builtin encoding)",
          std::strcmp(typeid(double).name(), "d") == 0);
    check("audio::Processor mangles to a NESTED name (starts with 'N', ends with 'E')",
          typeid(audio::Processor).name()[0] == 'N');

    // (2) STRUCT LAYOUT is ABI: member order + padding is part of the binary
    // interface. Two compilers/stdlibs that disagree on layout cannot share a
    // struct by pointer across a .so boundary.
    std::printf("\n(2) STRUCT LAYOUT (ABI: member order + padding are part of the contract):\n");
    std::printf("    sizeof(audio::Processor) = %zu   = int(%zu) + pad(%zu) + double(%zu)\n",
                sizeof(audio::Processor), sizeof(int),
                sizeof(audio::Processor) - sizeof(int) - sizeof(double), sizeof(double));
    std::printf("    alignof(audio::Processor) = %zu  (governed by the widest member, double)\n",
                alignof(audio::Processor));

    check("Processor layout: int(4) + pad(4) + double(8) == 16 bytes",
          sizeof(audio::Processor) == 16);
    check("Processor alignment == alignof(double) == 8 (widest member rules)",
          alignof(audio::Processor) == alignof(double) && alignof(double) == 8);

    // (3) VTABLE POINTER: a class with a VIRTUAL function carries a hidden vptr
    // (one sizeof(void*) slot pointing at the class's vtable). The vptr forces
    // the class alignment up to alignof(void*), which adds TAIL PADDING too.
    //   Engine = vptr(8) at off 0 + int channels(4) at off 8 + tail pad(4) = 16
    struct NoVirtual { int x; };
    std::printf("\n(3) VTABLE POINTER (the binary cost of a virtual function):\n");
    std::printf("    struct NoVirtual { int x; }        sizeof = %zu  alignof = %zu\n",
                sizeof(NoVirtual), alignof(NoVirtual));
    std::printf("    class  Engine     { virtual... }   sizeof = %zu  alignof = %zu\n",
                sizeof(audio::Engine), alignof(audio::Engine));
    std::printf("    Engine = vptr(%zu) + int channels(%zu) + tail pad(%zu) = %zu\n",
                sizeof(void*), sizeof(int),
                sizeof(audio::Engine) - sizeof(void*) - sizeof(int), sizeof(audio::Engine));
    std::printf("    (the vptr is the Itanium ABI polymorphism slot; it also raises alignment)\n");

    check("a class with a virtual function is larger than the same struct without",
          sizeof(audio::Engine) > sizeof(NoVirtual));
    check("Engine carries a vptr: sizeof(Engine) >= sizeof(void*) + sizeof(int)",
          sizeof(audio::Engine) >= sizeof(void*) + sizeof(int));
    check("Engine alignment == alignof(void*) == 8 (the vptr governs alignment)",
          alignof(audio::Engine) == alignof(void*) && alignof(void*) == 8);

    // (4) libstdc++ (GCC) vs libc++ (clang/Apple): the TWO C++ stdlib
    // implementations. They are NOT ABI-compatible (std::string / std::vector
    // layouts differ), so a whole program must use exactly one. Detected here.
    std::printf("\n(4) THE STDLIB ABI: libstdc++ (GCC) vs libc++ (clang/LLVM)\n");
    std::printf("    THIS binary is linked against: %s\n", STDLIB_NAME);
    std::printf("    detected via macro:            %s\n",
#if defined(_LIBCPP_VERSION)
                "_LIBCPP_VERSION is defined (libc++)"
#elif defined(__GLIBCXX__)
                "__GLIBCXX__ is defined (libstdc++)"
#else
                "neither macro defined"
#endif
    );
    std::printf("    libstdc++: GCC's implementation  (Linux default)\n");
    std::printf("    libc++    : clang/LLVM           (macOS/Apple default)\n");
    std::printf("    NOT ABI-compatible: std::string / std::vector LAYOUTS DIFFER.\n");
    std::printf("    A libstdc++ .so CANNOT be linked into a libc++ executable (and vice versa).\n");

    check("this TU's stdlib is detected via a real predefined macro", true);
#if defined(_LIBCPP_VERSION)
    check("this binary uses libc++ (_LIBCPP_VERSION defined; Apple/clang default)",
          STDLIB_VERSION != 0);
#elif defined(__GLIBCXX__)
    check("this binary uses libstdc++ (__GLIBCXX__ defined; GCC default)",
          STDLIB_VERSION != 0);
#endif
    check("libstdc++ (GCC) and libc++ (clang) are NOT ABI-compatible (never mix)", true);
    check("a whole C++ program must use exactly ONE stdlib implementation", true);
}

// === Section C — The Itanium C++ ABI + RPATH / RUNPATH =======================
//
// The Itanium C++ ABI is the de-facto name-mangling + layout standard used by
// GCC, clang, and every non-MSVC compiler. MSVC uses its own ABI (incompatible).
// RPATH/RUNPATH are embedded loader-search paths telling the dynamic loader
// where to find the .so/.dylib at runtime.
void sectionC() {
    sectionBanner("C — The Itanium C++ ABI + RPATH/RUNPATH");

    // (1) THE ITANIUM C++ ABI: decode a mangled symbol by hand. The grammar is
    // length-prefixed identifiers inside N...E nested-name delimiters.
    std::printf("(1) THE ITANIUM C++ ABI (de-facto; GCC + clang + Apple; NOT MSVC):\n");
    std::printf("    _Z               mangling prefix (\"this is a C++ symbol\")\n");
    std::printf("    N 3foo 3bar E i  nested: foo::bar(int)\n");
    std::printf("      N ... E          nested-name delimiters\n");
    std::printf("      3foo             namespace 'foo'   (digit = length of next id)\n");
    std::printf("      3bar             function  'bar'\n");
    std::printf("      i                parameter type 'int' (Section B builtins)\n");
    std::printf("    MSVC uses its OWN mangling (?-prefixed) — NOT cross-compatible with Itanium.\n");

    check("Itanium C++ ABI is used by GCC, clang, and Apple clang", true);
    check("MSVC's mangling/layout ABI is NOT compatible with the Itanium ABI", true);

    // (2) ABI TAGS: GCC's [[gnu::abi_tag("tag")]] mangles a versioned suffix onto
    // symbols so two ABI versions can coexist. The famous case is libstdc++'s
    // C++11 std::string (tagged [abi:cxx11]) living alongside the old one.
    std::printf("\n(2) ABI TAGS (GCC): versioned symbol suffixes for coexistence\n");
    std::printf("    GCC tags the C++11 std::string with a [abi:cxx11] suffix in the mangled name,\n");
    std::printf("    so an old (pre-C++11) libstdc++ symbol and the new one can coexist in ONE\n");
    std::printf("    process (e.g. old .so + new exe link without breaking each other).\n");

    check("GCC ABI tags let two ABI versions of a symbol coexist in one process", true);

    // (3) RPATH / RUNPATH: embedded loader-search paths. The dynamic loader
    // consults them (in addition to LD_LIBRARY_PATH / dyld paths / system dirs)
    // to find the .so/.dylib the executable needs at runtime.
    std::printf("\n(3) RPATH / RUNPATH (embedded loader-search paths in the binary):\n");
    std::printf("    DT_RPATH   : older; searched BEFORE LD_LIBRARY_PATH (NOT overridable by env)\n");
    std::printf("    DT_RUNPATH : newer (modern default); LD_LIBRARY_PATH takes precedence\n");
    std::printf("    set at LINK time:   c++ ... -Wl,-rpath,/abs/path\n");
    std::printf("    common idiom:       -Wl,-rpath,\\$ORIGIN   (search next to the executable)\n");
    std::printf("    inspect (NOT run here — subprocess is forbidden in a bundle):\n");
    std::printf("        macOS: otool -L <bin> ; Linux: ldd <bin> ; readelf -d <bin>\n");

    check("RPATH/RUNPATH are EMBEDDED in the binary at LINK time", true);
    check("RUNPATH is overridable by LD_LIBRARY_PATH; legacy RPATH is not", true);
    check("RPATH/RUNPATH tell the dynamic loader where to find the .so/.dylib", true);
}

// === Section D — Cross-compilation (--target) + packaging ====================
//
// Cross-compilation builds for a DIFFERENT platform (CPU/OS) than the build
// host. Packaging a library means choosing how to distribute it (header-only /
// static / dynamic) and how the consumer finds it (CMake find_package).
void sectionD() {
    sectionBanner("D — Cross-compilation (--target) + packaging");

    // (1) CROSS-COMPILATION: the --target=<triple> names the OUTPUT platform.
    std::printf("(1) CROSS-COMPILATION (--target=<triple>):\n");
    std::printf("    target triple = <CPU>-<vendor>-<OS>[-<libc/abi>]\n");
    std::printf("    clang --target=aarch64-apple-darwin    -> macOS ARM64 binary\n");
    std::printf("    clang --target=x86_64-linux-gnu        -> Linux x86_64 (glibc) binary\n");
    std::printf("    clang --target=wasm32-wasi             -> WebAssembly binary\n");
    std::printf("    The OUTPUT runs on the TARGET, NOT on the build host.\n");
    std::printf("    (GCC uses a separate cross-toolchain per target instead of --target.)\n");

    check("a target triple names the CPU-vendor-OS of the OUTPUT binary", true);
    check("a cross-compiled binary does NOT run on the build host", true);

    // (2) PACKAGING A LIBRARY: three distribution models. The consumer's
    // CMake find_package resolves to whichever the author shipped.
    std::printf("\n(2) PACKAGING A LIBRARY (three distribution models):\n");
    std::printf("    HEADER-ONLY : one .hpp; #include only; NO linking step; compiles into each TU;\n");
    std::printf("                  zero runtime dep; build-time bloat per includer (e.g. catch2)\n");
    std::printf("    STATIC (.a) : archive of compiled .o; linked INTO the exe; self-contained exe;\n");
    std::printf("                  big exe; library update forces a re-link (Section A)\n");
    std::printf("    DYNAMIC(.so): compiled .so/.dylib/.dll; loaded at runtime; small exe;\n");
    std::printf("                  runtime dep + ABI-compatible .so required (Sections A/B)\n");
    std::printf("    consumer side (CMake):\n");
    std::printf("        find_package(MyLib REQUIRED)\n");
    std::printf("        target_link_libraries(app PRIVATE MyLib::MyLib)   # static OR dynamic\n");

    check("header-only: no linking step, #include only, zero runtime dep", true);
    check("static (.a): linked into the exe (self-contained, big, re-link on update)", true);
    check("dynamic (.so): runtime dep, small exe, ABI-compatible .so required", true);
}

// === Section E — Cross-language: the single-static-binary advantage ==========
//
// C++ has genuine linking/ABI pain. Go and Rust largely AVOID it by producing a
// SINGLE STATIC binary by default — the headline deployment contrast.
void sectionE() {
    sectionBanner("E — Cross-language: the single-static-binary advantage");

    std::printf("C++ has genuine linking/ABI pain. Go and Rust largely AVOID it by producing\n");
    std::printf("a SINGLE STATIC binary by default. Node/TS sidesteps native linking entirely.\n\n");

    std::printf("    language | default binary        | linking/ABI pain\n");
    std::printf("    ---------|----------------------|------------------------------------------\n");
    std::printf("    C++      | dynamic (links libc++)| HIGH: ABI, name mangling, RPATH, stdlib mix\n");
    std::printf("    Go       | SINGLE STATIC binary  | NONE: every dep compiled into one file\n");
    std::printf("    Rust     | static (or musl)      | LOW: musl target = fully static binary\n");
    std::printf("    Node/TS  | no native linking     | N/A: modules are loaded by the JS runtime\n");

    std::printf("\n    Go:   CGO_ENABLED=0 go build            -> one self-contained executable\n");
    std::printf("    Rust: cargo build --target x86_64-unknown-linux-musl -> fully static\n");
    std::printf("    -> a Go/Rust binary is `scp`-deployable; a dynamic C++ binary is NOT\n");
    std::printf("       (it needs its .so/.dylib present + ABI-compatible at the destination).\n");

    check("Go produces a single static binary by default (CGO disabled)", true);
    check("Rust + the musl target produces a fully static binary", true);
    check("a dynamically-linked C++ binary is NOT scp-deployable (needs its .so + ABI)", true);
}

}  // namespace

int main() {
    std::printf("deployment_linking.cpp — Phase 8 bundle.\n");
    std::printf("Every ABI/layout value is computed by this file; linking/tradeoff facts are\n");
    std::printf("asserted as standard-fixed static facts. Compiled -std=c++23 -O2 -Wall\n");
    std::printf("-Wextra -Wpedantic; UB-free (just sanitize clean). stdlib: %s.\n", STDLIB_NAME);
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
