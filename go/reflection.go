//go:build ignore

// reflection.go — Phase 4 bundle.
//
// GOAL (one line): show, by printing every value, how Go's reflect package
// implements the three laws of reflection, struct-tag introspection, the
// addressability rule for mutation, and the runtime cost of reflection.
//
// This is the GROUND TRUTH for REFLECTION.md. Every number, table, and worked
// example in the guide is printed by this file. Change it -> re-run -> re-paste.
// Never hand-compute.
//
// Run:
//
//	go run reflection.go

package main

import (
	"fmt"
	"reflect"
	"strings"
	"testing"
)

const bannerWidth = 70

var banner = strings.Repeat("=", bannerWidth) // a const initializer cannot call a function, so this is a var

// sink prevents the compiler from optimizing the benchmark bodies away. It is
// only written to (package-level vars are exempt from the "declared and not
// used" check).
var sink any

// sectionBanner prints a clearly delimited section divider (the house style).
func sectionBanner(title string) {
	fmt.Printf("\n%s\nSECTION %s\n%s\n", banner, title, banner)
}

// check asserts an invariant and prints a uniform "[check] ... OK" line.
// On failure it panics (non-zero exit) so `just check` / `just sweep` catch it.
func check(description string, ok bool) {
	if !ok {
		panic("INVARIANT VIOLATED: " + description)
	}
	fmt.Printf("[check] %s: OK\n", description)
}

// Person is a struct carrying `json` struct tags, used by section C to show
// field enumeration + StructTag.Get. The tags are exactly what encoding/json
// reads (see REFLECTION.md "why encoding/json needs reflect").
type Person struct {
	Name    string `json:"name,omitempty"`
	Age     int    `json:"age"`
	Country string `json:"country"`
}

// mustSetPanic runs v.SetInt(n) and returns the recovered panic message.
// A deferred recover() catches the run-time panic so the program keeps running
// (see CONTROL_FLOW_DEFER). This is how the bundle asserts the "not
// addressable" panic WITHOUT crashing: Law 3 says Set on a non-addressable
// Value panics by design.
func mustSetPanic(v reflect.Value, n int64) (msg string, panicked bool) {
	defer func() {
		if r := recover(); r != nil {
			panicked = true
			msg = fmt.Sprintf("%v", r)
		}
	}()
	v.SetInt(n)
	return "", false
}

// sectionA pins Laws 1 & 2: an interface value round-trips through the
// reflection objects (TypeOf/ValueOf) and back to an interface (Value.Interface).
func sectionA() {
	sectionBanner("A — Laws 1 & 2: interface value <-> reflection object")

	// reflect.TypeOf and reflect.ValueOf take an `any`. Passing i boxes i into an
	// interface value; the functions unpack its (type, value) pair. This is Law 1:
	// "reflection goes from interface value to reflection object".
	i := 42
	t := reflect.TypeOf(i)
	v := reflect.ValueOf(i)
	fmt.Printf("i := %d  (boxed into `any` by TypeOf/ValueOf)\n", i)
	fmt.Printf("reflect.TypeOf(i)  -> Name=%-6q Kind=%v\n", t.Name(), t.Kind())
	fmt.Printf("reflect.ValueOf(i) -> Type=%v Int()=%d Kind=%v\n", v.Type(), v.Int(), v.Kind())

	// Law 2: "reflection goes from reflection object to interface value".
	// Value.Interface() boxes the value back into an `any`; a type assertion
	// recovers the concrete int.
	round := v.Interface().(int)
	fmt.Printf("v.Interface().(int) -> %d   (Law 2 round-trip back to interface)\n", round)

	check("reflect.TypeOf(42).Kind() == reflect.Int", t.Kind() == reflect.Int)
	check(`reflect.TypeOf(42).Name() == "int"`, t.Name() == "int")
	check("v.Type() == reflect.TypeOf(42) (the two objects agree)", v.Type() == reflect.TypeOf(42))
	check("Law 2 round-trip: v.Interface().(int) == 42", round == 42)
}

// sectionB classifies types at runtime via reflect.Kind (the category of a type:
// Int, String, Struct, Slice, Ptr, Map, Func, Chan, ...).
func sectionB() {
	sectionBanner("B — Kind: classifying types at runtime")

	// A SLICE of examples ranges in source order (deterministic). Only map
	// iteration is randomized in Go; a slice is stable, so no sorting is needed.
	type local struct{ X int }
	examples := []struct {
		name string
		val  any
		want reflect.Kind
	}{
		{"int", 7, reflect.Int},
		{"string", "hi", reflect.String},
		{"float64", 3.14, reflect.Float64},
		{"bool", true, reflect.Bool},
		{"[]int", []int{1, 2}, reflect.Slice},
		{"*int", (*int)(nil), reflect.Ptr},
		{"map[string]int", map[string]int{"a": 1}, reflect.Map},
		{"struct{X int}", local{X: 1}, reflect.Struct},
		{"func()", func() {}, reflect.Func},
		{"chan int", make(chan int), reflect.Chan},
	}
	fmt.Printf("%-16s %-10s %-10s %s\n", "value", "Kind()", "expected", "match")
	for _, e := range examples {
		k := reflect.TypeOf(e.val).Kind()
		fmt.Printf("%-16s %-10v %-10v %v\n", e.name, k, e.want, k == e.want)
	}

	// Note: (*int)(nil) is a TYPED nil pointer. The interface holds (type=*int,
	// value=nil), so TypeOf returns *int — it is NOT a nil interface. Contrast
	// with section F where reflect.TypeOf(nil) returns nil.
	check("Kind(int) == reflect.Int", reflect.TypeOf(7).Kind() == reflect.Int)
	check("Kind(string) == reflect.String", reflect.TypeOf("hi").Kind() == reflect.String)
	check("Kind([]int) == reflect.Slice", reflect.TypeOf([]int{1}).Kind() == reflect.Slice)
	check("Kind(*int) == reflect.Ptr", reflect.TypeOf((*int)(nil)).Kind() == reflect.Ptr)
	check("Kind(struct) == reflect.Struct", reflect.TypeOf(local{}).Kind() == reflect.Struct)
	check("Kind(map) == reflect.Map", reflect.TypeOf(map[string]int{}).Kind() == reflect.Map)
	check("Kind(func()) == reflect.Func", reflect.TypeOf(func() {}).Kind() == reflect.Func)
	check("Kind(chan int) == reflect.Chan", reflect.TypeOf(make(chan int)).Kind() == reflect.Chan)
}

// sectionC walks a struct's fields on BOTH sides: the static Type (StructField
// with Name/Type/Tag) and the live Value (reflect.Value.Field(i)). The Tag is
// parsed with StructTag.Get — exactly how encoding/json discovers field names.
func sectionC() {
	sectionBanner("C — Struct reflection: fields & struct tags")

	// TYPE side: t.Field(i) returns a StructField (metadata), no value.
	t := reflect.TypeOf(Person{})
	fmt.Printf("reflect.TypeOf(Person{}) -> Name=%q Kind=%v NumField=%d\n",
		t.Name(), t.Kind(), t.NumField())
	fmt.Printf("%-3s %-9s %-8s %-24s %s\n", "idx", "Name", "Type", "Tag (raw)", `Tag.Get("json")`)
	for i := 0; i < t.NumField(); i++ {
		f := t.Field(i)
		fmt.Printf("%-3d %-9s %-8v %-24q %q\n", i, f.Name, f.Type, string(f.Tag), f.Tag.Get("json"))
	}

	// VALUE side: reflect.ValueOf(p).Field(i) returns the field's live value.
	p := Person{Name: "Ada", Age: 36, Country: "UK"}
	pv := reflect.ValueOf(p)
	fmt.Println("value side — reflect.ValueOf(p).Field(i):")
	for i := 0; i < pv.NumField(); i++ {
		fv := pv.Field(i)
		fmt.Printf("  Field(%d) %s = %-6v (Kind=%v CanSet=%v)\n",
			i, t.Field(i).Name, fv.Interface(), fv.Kind(), fv.CanSet())
	}

	// Assert the metadata of a known field (the pinned value).
	nameField := t.Field(0)
	check(`field 0 Name == "Name"`, nameField.Name == "Name")
	check(`field 0 Type == reflect.TypeOf("")`, nameField.Type == reflect.TypeOf(""))
	check(`field 0 Tag.Get("json") == "name,omitempty"`, nameField.Tag.Get("json") == "name,omitempty")
	// FieldByName is what encoding/json uses to match a JSON key to a field.
	if ageField, ok := t.FieldByName("Age"); ok {
		check(`FieldByName("Age") found`, true)
		check(`FieldByName("Age").Tag.Get("json") == "age"`, ageField.Tag.Get("json") == "age")
	} else {
		check(`FieldByName("Age") found`, false)
	}
	// The value side is a COPY (ValueOf takes p by value), so no field is settable.
	check("reflect.Value field 0 value == \"Ada\"", pv.Field(0).Interface().(string) == "Ada")
	check("reflect.Value field 0 CanSet == false (ValueOf(p) is a copy)", !pv.Field(0).CanSet())
}

// sectionD pins Law 3: to MODIFY the real value via reflection, the Value must
// be SETTABLE, which means ADDRESSABLE. You get an addressable Value only from a
// pointer: reflect.ValueOf(&n).Elem(). SetInt on a by-value Value panics.
func sectionD() {
	sectionBanner("D — Law 3: to modify, the Value must be addressable")

	// WRONG: ValueOf(n) receives a COPY of n. The copy has no address -> not
	// settable -> SetInt panics "value obtained using unaddressable value".
	n := 42
	vCopy := reflect.ValueOf(n)
	fmt.Printf("reflect.ValueOf(n=%d).CanSet() = %v   (n passed by value -> copy)\n", n, vCopy.CanSet())
	msg, panicked := mustSetPanic(vCopy, 99)
	fmt.Printf("reflect.ValueOf(n).SetInt(99) -> panicked=%v\n", panicked)
	fmt.Printf("panic message: %s\n", msg)

	// RIGHT: pass a POINTER, then .Elem() dereferences inside reflect. The
	// resulting Value points at the real n -> addressable -> settable.
	vAddr := reflect.ValueOf(&n).Elem()
	fmt.Printf("reflect.ValueOf(&n).Elem().CanSet() = %v   (pointer deref -> real n)\n", vAddr.CanSet())
	vAddr.SetInt(99)
	fmt.Printf("after vAddr.SetInt(99) -> n=%d   (Law 3: the real variable changed)\n", n)

	check("reflect.ValueOf(n).CanSet() == false (copy, not addressable)", !vCopy.CanSet())
	check("SetInt on a non-addressable Value panics", panicked)
	check(`panic message contains "unaddressable"`, strings.Contains(msg, "unaddressable"))
	check("reflect.ValueOf(&n).Elem().CanSet() == true", vAddr.CanSet())
	check("vAddr.SetInt(99) -> n == 99 (Law 3)", n == 99)
}

// sectionE measures the cost of reflection with the testing package's allocation
// counter (deterministic: same alloc count every run, unlike ns/op which is
// timing-dependent and therefore never printed). Two findings: reflect.New
// allocates more than the typed new(), but a scalar reflect read is 0-alloc —
// escape analysis wins; the reflect cost there is CPU dispatch, not heap.
func sectionE() {
	sectionBanner("E — The cost: reflection allocates & dispatches at runtime")

	// Creating a value of a runtime-known type: reflect.New vs typed new().
	// Both produce a *int boxed into `any`. AllocsPerRun is deterministic.
	allocTypedNew := testing.AllocsPerRun(1000, func() {
		sink = new(int)
	})
	allocReflectNew := testing.AllocsPerRun(1000, func() {
		t := reflect.TypeOf(int(0))
		sink = reflect.New(t)
	})
	fmt.Printf("new(int)         allocs/op = %v\n", allocTypedNew)
	fmt.Printf("reflect.New(int) allocs/op = %v\n", allocReflectNew)
	fmt.Printf("reflect overhead = %.0f extra alloc/op\n", allocReflectNew-allocTypedNew)

	// Expert surprise: a scalar reflect read is allocation-free on modern Go.
	allocReflectRead := testing.AllocsPerRun(1000, func() {
		v := reflect.ValueOf(7)
		sink = v.Int()
	})
	fmt.Printf("reflect.ValueOf(7).Int() allocs/op = %v   (escape analysis: 0 allocs)\n", allocReflectRead)
	fmt.Println("note: ns/op is NOT printed — it is timing and non-deterministic;")
	fmt.Println("      reflect is still SLOWER per op (runtime type dispatch, no inlining).")

	check("reflect.New(int) allocs/op > 0", allocReflectNew > 0)
	check("reflect.New(int) allocs/op > new(int) allocs/op", allocReflectNew > allocTypedNew)
	check("scalar reflect Int() read is 0-alloc (escape analysis)", allocReflectRead == 0)
}

// sectionF pins the zero-value behavior: a nil interface argument has no dynamic
// type, so TypeOf returns nil (the nil reflect.Type) and ValueOf returns the
// zero reflect.Value whose IsValid() is false.
func sectionF() {
	sectionBanner("F — Zero-value reflect: nil interface & the zero Value")

	// reflect.TypeOf takes `any`. The literal nil is a nil interface (no type),
	// so there is no Type to return -> TypeOf yields nil.
	nilType := reflect.TypeOf(nil)
	fmt.Printf("reflect.TypeOf(nil) == nil ? %v   (nil interface has no dynamic type)\n", nilType == nil)

	// reflect.ValueOf(nil) returns the ZERO reflect.Value (a sentinel, not a nil
	// pointer). IsValid() distinguishes it from a real Value.
	nilVal := reflect.ValueOf(nil)
	fmt.Printf("reflect.ValueOf(nil).IsValid() = %v   (the zero Value)\n", nilVal.IsValid())

	// The zero Value is also what `var zv reflect.Value` produces.
	var zv reflect.Value
	fmt.Printf("var zv reflect.Value; zv.IsValid() = %v\n", zv.IsValid())

	// Contrast: a real Value is valid.
	fmt.Printf("reflect.ValueOf(42).IsValid() = %v\n", reflect.ValueOf(42).IsValid())

	check("reflect.TypeOf(nil) == nil (no dynamic type)", reflect.TypeOf(nil) == nil)
	check("reflect.ValueOf(nil).IsValid() == false", !reflect.ValueOf(nil).IsValid())
	check("zero reflect.Value IsValid() == false", !zv.IsValid())
	check("reflect.ValueOf(42).IsValid() == true", reflect.ValueOf(42).IsValid())
}

func main() {
	fmt.Println("reflection.go — Phase 4 bundle.")
	fmt.Println("Every value below is computed by this file; the .md guide pastes")
	fmt.Println("it verbatim. Nothing is hand-computed.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionF()
	sectionBanner("DONE — all sections printed")
}
