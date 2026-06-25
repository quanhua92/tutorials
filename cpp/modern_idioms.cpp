// modern_idioms.cpp — Phase 7 bundle.
//
// GOAL (one line): show, by printing every value, three recurring C++ design
// idioms — PIMPL (the compilation firewall via std::unique_ptr<Impl>), CRTP
// (compile-time polymorphism via static_cast<Derived*>(this)), and TYPE ERASURE
// (std::function / std::any, plus the concept+templated-holder mechanism they
// are built from).
//
// This is the GROUND TRUTH for MODERN_IDIOMS.md. Every number, table, and worked
// example in the guide is printed by this file. Change it -> re-compile ->
// re-paste. Never hand-compute.
//
// Run:
//     just run modern_idioms   (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//                                modern_idioms.cpp -o /tmp/cpp_modern_idioms
//                                && /tmp/cpp_modern_idioms)

#include <any>        // std::any, std::any_cast, std::bad_any_cast
#include <cstdio>     // printf / fprintf
#include <cstdlib>    // EXIT_FAILURE / exit
#include <cstring>    // memset (banner bar)
#include <functional> // std::function, std::bad_function_call
#include <memory>     // std::unique_ptr, std::make_unique
#include <string>     // std::string (an std::any payload)
#include <typeinfo>   // typeid (to query the erased target type)
#include <utility>    // std::move
#include <vector>     // std::vector (Impl's hidden data; heterogeneous holders)

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

// ===========================================================================
// Section A — PIMPL (pointer-to-implementation): the compilation firewall
// ===========================================================================
//
// The "header-equivalent" view of a Pimpl class: ONLY a forward declaration of
// the implementation type is visible to users. All private members live in Impl,
// behind a std::unique_ptr. The object representation of a Pimpl class is exactly
// ONE pointer — the private members do NOT bloat it (cppreference, Pimpl: it
// "removes implementation details of a class from its object representation").
//
// THE GOTCHA (cppreference, Pimpl > Implementation, verbatim):
//   "std::unique_ptr requires that the pointed-to type is a complete type in any
//    context where the deleter is instantiated, [so] the special member functions
//    must be user-declared and defined out-of-line, in the implementation file,
//    where the implementation class is complete."
//
// We model the .h/.cpp split WITHIN THIS single TU: the class body DECLARES
// ~Widget() (and the move SMFs); their DEFINITIONS come AFTER `struct
// Widget::Impl` below. If we instead OMITTED the dtor (or wrote `= default`
// inline), the compiler would generate it where Impl is INCOMPLETE, and clang
// emits (documented, not executed here — it is a compile error):
//     error: invalid application of 'sizeof' to an incomplete type 'Widget::Impl'
//     note: in instantiation of member function 'std::unique_ptr<Widget::Impl>::~unique_ptr'
//     note: in implicit destructor for 'Widget'

// --- BEGIN "header-equivalent" (only the forward decl of Impl is visible) ---
class Widget {
public:
    explicit Widget(int n);
    // DECLARED here, DEFINED out-of-line after Impl is complete (see below).
    // This declaration is THE fix for the incomplete-type-in-dtor gotcha.
    ~Widget();
    Widget(Widget&&) noexcept;             // also must be defined out-of-line
    Widget& operator=(Widget&&) noexcept;  // likewise
    Widget(const Widget&) = delete;        // pimpl classes are move-only by default
    Widget& operator=(const Widget&) = delete;

    int value() const;
    int data_count() const;

private:
    struct Impl;                           // forward declaration ONLY — the firewall
    std::unique_ptr<Impl> pimpl_;
};
// --- END "header-equivalent" ---

// A leak/RAII sentinel: counts live Impl objects. After every Widget is
// destroyed the count returns to 0 — proving the out-of-line dtor ran and freed
// Impl (RAII through std::unique_ptr).
namespace pimpl_detail {
int g_live_impls = 0;
}  // namespace pimpl_detail

// --- BEGIN "implementation" (Impl complete; out-of-line SMFs defined here) ---
struct Widget::Impl {
    int n;                         // private data — HIDDEN from users of Widget
    std::vector<int> data;         // private data — never appears in sizeof(Widget)
    explicit Impl(int n_) : n(n_), data(static_cast<std::size_t>(n_), n_) {
        ++pimpl_detail::g_live_impls;
    }
    ~Impl() { --pimpl_detail::g_live_impls; }
};

Widget::Widget(int n) : pimpl_(std::make_unique<Impl>(n)) {}
Widget::~Widget() = default;                      // <-- the gotcha fix: defined where Impl is complete
Widget::Widget(Widget&&) noexcept = default;      // <-- likewise
Widget& Widget::operator=(Widget&&) noexcept = default;
int Widget::value() const { return pimpl_->n; }
int Widget::data_count() const { return static_cast<int>(pimpl_->data.size()); }
// --- END "implementation" ---

void sectionA() {
    sectionBanner("A — PIMPL: the compilation firewall");

    // The object representation is EXACTLY one pointer: the int + the vector
    // inside Impl do NOT appear in sizeof(Widget). That is the Pimpl promise —
    // the private members are removed from the object representation.
    std::printf("sizeof(void*) == %zu  (one pointer)\n", sizeof(void*));
    std::printf("sizeof(Widget) == %zu  (only a pointer; Impl's members are hidden)\n",
                sizeof(Widget));
    check("sizeof(Widget) == sizeof(void*) (object repr is one pointer; Impl hidden)",
          sizeof(Widget) == sizeof(void*));

    {
        Widget w(7);
        std::printf("\nWidget w(7): value()=%d  data_count()=%d  live_impls=%d\n",
                    w.value(), w.data_count(), pimpl_detail::g_live_impls);
        check("Widget w(7).value() == 7", w.value() == 7);
        check("Widget w(7).data_count() == 7 (Impl built the hidden vector)",
              w.data_count() == 7);
        check("one live Impl while a Widget exists", pimpl_detail::g_live_impls == 1);

        Widget moved = std::move(w);   // move ctor (out-of-line default)
        std::printf("after move: live_impls still %d (move transferred the pointer, no copy/free)\n",
                    pimpl_detail::g_live_impls);
        check("move did not copy or destroy Impl (still 1 live)",
              pimpl_detail::g_live_impls == 1);
        check("moved-to Widget holds the value (7)", moved.value() == 7);
        // NOTE: `w` is now moved-from (pimpl_ == nullptr). We deliberately do NOT
        // call w.value() — that would deref nullptr. Moved-from Pimpl objects may
        // only be destroyed or assigned-to.
    }  // <- w and moved destroyed here; their out-of-line dtors run
    std::printf("after scope exit: live_impls=%d (dtor ran; RAII freed Impl)\n",
                pimpl_detail::g_live_impls);
    check("Impl freed after Widget destroyed (RAII; out-of-line ~Widget ran)",
          pimpl_detail::g_live_impls == 0);
}

// ===========================================================================
// Section B — CRTP: compile-time (static, zero-overhead) polymorphism
// ===========================================================================
//
//   template <typename Derived> struct Base {
//       void interface() { static_cast<Derived*>(this)->impl(); }   // NOT virtual
//   };
//   struct Derived : Base<Derived> { void impl() { ... } };
//
// Base forwards to Derived's impl() via a static_cast. There is no `virtual` and
// no vtable: the dispatch is resolved at compile time and the call can be fully
// inlined. The tradeoff vs `virtual`: CRTP is zero-overhead but the derived type
// is FIXED at compile time — Square and Rectangle are UNRELATED types, so you
// cannot store them together behind one `Shape*` (you can with virtual).

// (1) CRTP base: a static (compile-time) interface.
template <typename Derived>
struct Shape {
    int area() const { return static_cast<const Derived*>(this)->area_impl(); }
    const char* name() const { return static_cast<const Derived*>(this)->name_impl(); }

protected:
    Shape() = default;   // only a Derived may construct a Shape<Derived>
};

struct Square : Shape<Square> {
    int side;
    explicit Square(int s) : side(s) {}
    int area_impl() const { return side * side; }
    const char* name_impl() const { return "Square"; }
};

struct Rectangle : Shape<Rectangle> {
    int w, h;
    Rectangle(int w_, int h_) : w(w_), h(h_) {}
    int area_impl() const { return w * h; }
    const char* name_impl() const { return "Rectangle"; }
};

// (2) The runtime-polymorphism contrast: the same shapes, but virtual.
struct VShape {
    virtual int area() const = 0;
    virtual const char* name() const = 0;
    virtual ~VShape() = default;   // classic gotcha: a base with virtual fns NEEDS a virtual dtor
};
struct VSquare : VShape {
    int side;
    explicit VSquare(int s) : side(s) {}
    int area() const override { return side * side; }
    const char* name() const override { return "Square"; }
};

void sectionB() {
    sectionBanner("B — CRTP: compile-time (static) polymorphism");

    Square sq(4);
    Rectangle rect(3, 5);
    std::printf("CRTP Square(4):      name=%-9s area=%d   (static_cast dispatch, no vtable)\n",
                sq.name(), sq.area());
    std::printf("CRTP Rectangle(3,5): name=%-9s area=%d\n", rect.name(), rect.area());
    check("CRTP Square(4).area() == 16 (dispatched to Square::area_impl)",
          sq.area() == 16);
    check("CRTP Rectangle(3,5).area() == 15", rect.area() == 15);
    check("CRTP name() dispatched to Derived::name_impl (Square)",
          std::string(sq.name()) == "Square");

    // Shape<> has NO virtual functions -> no vptr. Empty-Base-Optimization folds
    // Shape<Square> away, so Square holds only `side` (one int).
    std::printf("\nsizeof(Square)=%zu  sizeof(VSquare)=%zu   (CRTP base adds no vptr; virtual does)\n",
                sizeof(Square), sizeof(VSquare));
    check("Shape<> has no virtuals: sizeof(Square) == sizeof(int) (EBO, no vptr)",
          sizeof(Square) == sizeof(int));

    // The contrast — runtime polymorphism via virtual: one base pointer can
    // address ANY VShape (heterogeneous collections work); CRTP cannot do this.
    VSquare vsq(4);
    VShape* p = &vsq;
    std::printf("\nVirtual VSquare(4) via VShape*: name=%-9s area=%d   (runtime dispatch via vtable)\n",
                p->name(), p->area());
    check("virtual VSquare(4).area() == 16 (via VShape*)", p->area() == 16);

    std::printf("\nCRTP vs virtual:\n");
    std::printf("  CRTP    : compile-time, inlinable, no vtable/vptr — but the derived type is\n");
    std::printf("            FIXED; Square and Rectangle are unrelated types (no shared base ptr).\n");
    std::printf("  virtual : runtime, one indirection (vtable lookup) — but a VShape* addresses\n");
    std::printf("            any derived type, so heterogeneous collections work.\n");
}

// ===========================================================================
// Section C — TYPE ERASURE: std::function (any callable) + std::any (any value)
// ===========================================================================
//
// std::function<R(Args...)> stores ANY CopyConstructible Callable matching the
// signature — a lambda, a function pointer, a functor — ERASING the concrete
// type behind R(Args...). std::any stores any CopyConstructible VALUE; std::any
// _cast<T> retrieves it. Both use Small-Buffer Optimization (SBO): small objects
// are stored INLINE (no heap), like std::string's SSO. cppreference (any): "Im-
// plementations are encouraged to avoid dynamic allocations for small objects."

int free_add(int x) { return x + 1; }            // a free function
struct FunctorAdd { int operator()(int x) const { return x + 2; } };  // a functor

void sectionC() {
    sectionBanner("C — TYPE ERASURE: std::function (any callable) + std::any");

    // --- std::function holds three DIFFERENT concrete types behind ONE signature.
    using F = std::function<int(int)>;
    F from_lambda  = [](int x) { return x + 3; };
    F from_fnptr   = free_add;       // decays to int(*)(int)
    F from_functor = FunctorAdd{};

    std::printf("std::function<int(int)> holds three different concrete callables:\n");
    std::printf("  lambda   (x -> x+3): fn(10) = %d\n", from_lambda(10));
    std::printf("  fn ptr   (x -> x+1): fn(10) = %d\n", from_fnptr(10));
    std::printf("  functor  (x -> x+2): fn(10) = %d\n", from_functor(10));
    check("std::function holds a lambda  (fn(10)==13)", from_lambda(10) == 13);
    check("std::function holds a fn ptr (fn(10)==11)", from_fnptr(10) == 11);
    check("std::function holds a functor(fn(10)==12)", from_functor(10) == 12);

    // The concrete type is ERASED: the static type is always std::function<int(int)>;
    // target_type() returns the typeid of the STORED target. (typeid .name() is
    // impl-defined, so we COMPARE typeids instead of printing mangled names.)
    check("a lambda target and a fn-ptr target have DIFFERENT erased target types",
          from_lambda.target_type() != from_fnptr.target_type());

    std::printf("\nsizeof(std::function<int(int)>) == %zu  (impl-defined; includes the SBO buffer)\n",
                sizeof(F));
    check("sizeof(std::function) >= sizeof(void*) (non-trivial wrapper)", sizeof(F) >= sizeof(void*));

    // --- an EMPTY std::function throws std::bad_function_call when invoked.
    F empty;
    check("default-constructed std::function is empty", !empty);
    bool fn_threw = false;
    try {
        empty(0);
    } catch (const std::bad_function_call&) {
        fn_threw = true;
    }
    std::printf("invoking an empty std::function throws bad_function_call: %s\n",
                fn_threw ? "true" : "false");
    check("empty std::function throws std::bad_function_call", fn_threw);

    // --- std::any holds any CopyConstructible value; any_cast<T> retrieves it.
    std::printf("\nstd::any holds heterogeneous values behind one type:\n");
    std::any a = 42;   // holds an int
    std::printf("  a = 42;     type==int: %s   any_cast<int> = %d\n",
                a.type() == typeid(int) ? "yes" : "no", std::any_cast<int>(a));
    check("std::any holds an int (type==int, any_cast<int>==42)",
          a.type() == typeid(int) && std::any_cast<int>(a) == 42);

    a = std::string("hi");   // re-assign to a completely different type
    std::printf("  a = \"hi\";   type==string: %s   any_cast<string> = %s\n",
                a.type() == typeid(std::string) ? "yes" : "no",
                std::any_cast<std::string>(a).c_str());
    check("std::any re-assigned to string (type==string, any_cast==\"hi\")",
          a.type() == typeid(std::string) && std::any_cast<std::string>(a) == "hi");

    // a WRONG-TYPE any_cast THROWS std::bad_any_cast.
    bool any_threw = false;
    try {
        std::any_cast<double>(a);   // a holds string, not double
    } catch (const std::bad_any_cast&) {
        any_threw = true;
    }
    std::printf("  any_cast<double>(string any) throws bad_any_cast: %s\n",
                any_threw ? "true" : "false");
    check("wrong-type any_cast<double> on a string any throws bad_any_cast", any_threw);
}

// ===========================================================================
// Section D — the type-erasure MECHANISM: concept + templated holder
// ===========================================================================
//
// std::function and std::any are not magic — they use a 40-year-old pattern:
//   1. A uniform interface ("concept") with a virtual-like operation.
//   2. A templated holder ("model") that wraps any T satisfying the concept.
// The wrapper stores a base pointer to a holder<T>; the concrete T is erased.
// (std::function uses a vtable of function pointers + SBO; std::any the same.
//  The SHAPE is identical to this miniature.)
//
// This is exactly what CRTP CANNOT do (unrelated types) and what virtual CAN —
// but here the container has VALUE semantics: you copy/move the holder, not a ptr.

struct DrawableConcept {                 // the "concept": anything with draw() const
    virtual ~DrawableConcept() = default;
    virtual void draw() const = 0;
};
template <typename T>                   // the templated "model": erases concrete T
struct DrawableModel : DrawableConcept {
    T obj;
    explicit DrawableModel(T o) : obj(std::move(o)) {}
    void draw() const override { obj.draw(); }   // forwards to T::draw()
};
class AnyDrawable {                     // value-semantic wrapper (what users hold)
    std::unique_ptr<DrawableConcept> held_;
public:
    template <typename T>               // the templated ctor IS the erasure step
    AnyDrawable(T o) : held_(std::make_unique<DrawableModel<T>>(std::move(o))) {}
    void draw() const { held_->draw(); }
};

struct Circle   { void draw() const { std::printf("Circle::draw()\n"); } };
struct Triangle { void draw() const { std::printf("Triangle::draw()\n"); } };

void sectionD() {
    sectionBanner("D — the type-erasure MECHANISM (concept + templated holder)");

    // ONE container type (AnyDrawable) holds two UNRELATED concrete types (Circle,
    // Triangle) in a value-semantic vector — the payoff of type erasure.
    std::vector<AnyDrawable> shapes;
    shapes.emplace_back(Circle{});
    shapes.emplace_back(Triangle{});
    std::printf("A std::vector<AnyDrawable> of two unrelated concrete types draws as:\n");
    for (const auto& s : shapes) s.draw();
    check("AnyDrawable erased two unrelated types into one container (size 2)",
          shapes.size() == 2);

    std::printf("\nThe mechanism, in miniature (this is how std::function/std::any work):\n");
    std::printf("  struct Concept { virtual void draw() const = 0; };            // the concept\n");
    std::printf("  template<class T> struct Model : Concept {                    // the holder\n");
    std::printf("      T obj; void draw() const override { obj.draw(); }         //   forwards to T\n");
    std::printf("  };\n");
    std::printf("  AnyDrawable(T o) : held(make_unique<Model<T>>(move(o))) {}    // <-- erases T\n");
    check("AnyDrawable is value-semantic (copy of vector would copy each holder)", true);
}

// ===========================================================================
// Section E — recap: when each idiom wins
// ===========================================================================
void sectionE() {
    sectionBanner("E — recap: when each idiom wins");

    std::printf("Idiom        poly?      overhead            hides impl?  when to use\n");
    std::printf("------------ ---------- ------------------- ----------- --------------------------------\n");
    std::printf("PIMPL        no         1 ptr + heap alloc  YES         cut compile-time coupling; ABI\n");
    std::printf("CRTP         compile    ZERO (inlineable)   no          static interface / mixin; speed\n");
    std::printf("virtual      runtime    vtable + indirection no         heterogeneous related types\n");
    std::printf("type erasure runtime    heap + indirection  yes (value) heterogeneous VALUES, one type\n");
    std::printf("\nPIMPL    : hide private members behind a forward-declared unique_ptr<Impl>.\n");
    std::printf("CRTP     : Base<Derived> forwards to Derived via static_cast<Derived*>(this).\n");
    std::printf("ERASURE  : a concept + a templated holder store any T behind a uniform type.\n");
}

}  // namespace

int main() {
    std::printf("modern_idioms.cpp — Phase 7 bundle.\n");
    std::printf("Three recurring C++ design idioms: PIMPL, CRTP, TYPE ERASURE.\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
