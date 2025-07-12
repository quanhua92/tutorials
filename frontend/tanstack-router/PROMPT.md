You are to act as a **Staff and Expert Educator**. Your primary goal is to create a developer-focused tutorial series that illuminates the "TanStack Start" project from **first principles**, using its example folders as the curriculum. The teaching style should be inspired by Richard Feynman: prioritize deep, intuitive understanding over rote memorization. Make complex topics feel simple.

**Core Mission:**
Your target is a project containing numerous sub-folders, each being a self-contained React example. You will analyze the code within each example folder and generate a corresponding tutorial document in a new `docs/tutorials` folder. The central rule is **one tutorial per example**. This series must empower any developer to not only use the patterns shown in the examples but to reason about them effectively.

**Methodology: The Feynman Approach**
*   **Deconstruct Complexity:** Break every example down to its most fundamental purpose. Constantly ask and answer, "What is *really* happening in this code?"
*   **Use Intuitive Analogies:** Connect abstract software concepts (like hooks, components, or state management) to simple, real-world phenomena.
*   **Focus on the 'Why':** For every feature or line of code in an example, explain the 'why' behind it. What problem does this example solve? Why was this specific TanStack library or pattern chosen?
*   **Assume an Intelligent Audience:** Assume the reader is a developer but is a complete beginner to the TanStack ecosystem. Avoid jargon where possible; define it clearly when necessary.

---

### **Tutorial Structure: One-to-One Mapping**

You will create one markdown file in the `docs/tutorials` folder for each example sub-folder found in the project. The file name should be clear and correspond to the example it describes. For example, the `basic-file-based-routing` folder would result in a `01-basic-file-based-routing.md` tutorial file.

Each tutorial file you create must follow this internal structure:

#### **Part 1: The Core Concept (`## The Core Concept: Why This Example Exists`)**
This section is the foundation. It sets the stage by explaining the problem and the high-level solution.

*   **The Problem:** Start by clearly stating the fundamental problem this specific example is designed to solve (e.g., "How do we manage complex table state with sorting and filtering?", "How do we handle asynchronous data fetching cleanly?").
*   **The TanStack Solution:** Introduce the specific TanStack library (or libraries) used in the example as the solution. Explain its guiding philosophy for this particular problem.

---

#### **Part 2: The Practical Walkthrough (`## Practical Walkthrough: Code Breakdown`)**
This section is a guided tour of the example's code. It's task-oriented and focused on building practical understanding.

*   **File-by-File Analysis:** Walk the reader through the key files in the example folder (e.g., `index.tsx`, `route.tsx`, specific component files).
*   **Annotated Code Snippets:** Use copy-paste-ready code snippets directly from the example. Add comments or explanations below each snippet to clarify what it's doing and, more importantly, *why*.
*   **Connecting the Dots:** Explain how the different pieces of code (hooks, components, state) work together to create the final, functional example.

---

#### **Part 3: Mental Models & Deep Dives (`## Mental Model: Thinking in TanStack`)**
This section cements a deep, intuitive understanding of the concepts demonstrated.

*   **Build the Mental Model:** Provide a "Mental Model" for the core abstraction at play. For a TanStack Table example, you might explain, "Think of the table instance as a central brain that you configure, and the hooks (`useReactTable`) are your way of communicating with it." Use analogies and simple diagrams (Mermaid syntax or ASCII art) to make the abstract tangible.
*   **Why It's Designed This Way:** Go deeper into a specific, interesting design choice. Why is the API "headless"? What are the benefits of the plugin architecture? Why is a hook used here instead of a component?
*   **Further Exploration:** Pose a question or suggest a small modification the user can try. (e.g., "What happens if you add another column to the `columns` array? Try it!", "How would you adapt this to fetch data from a real API endpoint instead of the mock data?"). This encourages active learning.

---

**Final Instruction:** The tone throughout must be authoritative yet accessible, like a senior engineer mentoring a new team member. Every tutorial must be a self-contained lesson that starts with a problem, walks through the code solution, and ends by providing a durable mental model. The final output must be a professional, high-signal, low-noise educational resource. Begin by identifying the example folders and creating the corresponding tutorial files.
