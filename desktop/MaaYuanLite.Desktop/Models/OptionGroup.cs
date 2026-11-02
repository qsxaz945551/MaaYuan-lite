namespace MaaYuanLite.Desktop.Models;

/// <summary>One editable field of an "input" option group.</summary>
public sealed class OptionField
{
    public string Name { get; init; } = "";
    public string Label { get; init; } = "";
    public string Value { get; init; } = "";
}

/// <summary>One option group as returned by GET /api/task-options.</summary>
public sealed class OptionGroup
{
    public string TaskName { get; init; } = "";
    public string Group { get; init; } = "";
    public string Type { get; init; } = "select";
    public int Depth { get; init; }
    public string Description { get; init; } = "";
    public string Label { get; init; } = "";
    public List<string> Cases { get; init; } = new();
    public int Selected { get; init; }
    public List<OptionField> Fields { get; init; } = new();

    /// <summary>True when the two cases should render as a switch.</summary>
    public bool IsSwitch =>
        Type == "switch" ||
        (Cases.Count == 2 && Cases.Any(c => c.Equals("Yes", StringComparison.OrdinalIgnoreCase)));

    /// <summary>Index that means "on": Yes when present, else the second case.</summary>
    public int OnIndex
    {
        get
        {
            var index = Cases.FindIndex(c => c.Equals("Yes", StringComparison.OrdinalIgnoreCase));
            if (index >= 0)
            {
                return index;
            }
            return Cases.Count > 1 ? 1 : 0;
        }
    }

    public int OffIndex
    {
        get
        {
            for (var i = 0; i < Cases.Count; i++)
            {
                if (i != OnIndex)
                {
                    return i;
                }
            }
            return OnIndex;
        }
    }
}
