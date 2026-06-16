using System;
using System.Collections.Generic;
using System.Linq;
using AutumnDesktop.DesignSystem;
using AutumnDesktop.Models;
using Microsoft.UI.Text;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.UI;

namespace AutumnDesktop.Chat;

/// <summary>
/// Compact pipeline timeline: workspace-coloured 6 px pill capsules + optional
/// agent/tool/4D chips. Mirrors PipelineStripView.swift in the macOS client.
/// Active-stage capsules pulse at 700 ms intervals via a DispatcherTimer.
/// </summary>
public sealed partial class PipelineStripView : UserControl
{
    private readonly List<Border> _activeItems = new();
    private readonly DispatcherTimer _pulseTimer = new() { Interval = TimeSpan.FromMilliseconds(700) };
    private bool _pulsed;

    public PipelineStripView()
    {
        InitializeComponent();
        _pulseTimer.Tick += OnPulseTick;
    }

    public static readonly DependencyProperty TraceProperty = DependencyProperty.Register(
        nameof(Trace), typeof(WorkflowTrace), typeof(PipelineStripView),
        new PropertyMetadata(null, (d, _) => ((PipelineStripView)d).Rebuild()));

    public WorkflowTrace? Trace
    {
        get => (WorkflowTrace?)GetValue(TraceProperty);
        set => SetValue(TraceProperty, value);
    }

    private void Rebuild()
    {
        StagesPanel.Children.Clear();
        _activeItems.Clear();
        _pulseTimer.Stop();
        _pulsed = false;

        if (Trace is null) return;

        foreach (var stage in Trace.Stages.Where(s => s.KindOrStage != "tool"))
        {
            var capsule = MakeCapsule(stage);
            if (stage.Status == "active") _activeItems.Add(capsule);
            StagesPanel.Children.Add(capsule);
        }

        if (Trace.Stages.Any(s => s.KindOrStage == "push"))
            StagesPanel.Children.Add(MakeChip("4D", Autumn.Colors.Memory));
        if (Trace.AgentStageCount > 0)
            StagesPanel.Children.Add(MakeChip("Agent", Autumn.Colors.Warning));
        if (Trace.ToolStageCount > 0)
            StagesPanel.Children.Add(MakeChip($"⚒ {Trace.ToolStageCount}", Autumn.Colors.Clay));

        if (_activeItems.Count > 0)
            _pulseTimer.Start();
    }

    private static Border MakeCapsule(WorkflowStage stage)
    {
        var color = Autumn.Colors.Workspace(stage.Workspace);
        var width = stage.KindOrStage == "push" ? 10.0
            : (stage.Id.EndsWith(".select") || stage.Id.EndsWith(".final_check")) ? 22.0
            : 16.0;

        var border = new Border { Width = width, Height = 6, CornerRadius = new CornerRadius(999) };
        ToolTipService.SetToolTip(border, BuildTooltip(stage));

        switch (stage.Status)
        {
            case "completed":
                border.Background = new SolidColorBrush(color);
                break;
            case "active":
                border.Background = new SolidColorBrush(color);
                break;
            case "failed":
                border.Background = new SolidColorBrush(Autumn.Colors.Danger);
                break;
            default: // pending — hairline outline only
                border.BorderBrush = new SolidColorBrush(
                    Color.FromArgb(0x80, color.R, color.G, color.B));
                border.BorderThickness = new Thickness(1);
                break;
        }

        return border;
    }

    private static Border MakeChip(string text, Color color)
    {
        var bg = Color.FromArgb(0x24, color.R, color.G, color.B);
        return new Border
        {
            CornerRadius = new CornerRadius(999),
            Padding = new Thickness(6, 1, 6, 1),
            Background = new SolidColorBrush(bg),
            Child = new TextBlock
            {
                Text = text,
                FontSize = 9,
                FontWeight = FontWeights.SemiBold,
                Foreground = new SolidColorBrush(color),
                VerticalAlignment = VerticalAlignment.Center,
            },
        };
    }

    private static string BuildTooltip(WorkflowStage stage)
    {
        var parts = new List<string> { $"{stage.Workspace.ToUpperInvariant()} · {stage.Title}" };
        var dur = Autumn.Format.Duration(stage.DurationMs);
        if (dur.Length > 0) parts.Add(dur);
        var tok = Autumn.Format.Tokens(stage.PromptTokens, stage.CompletionTokens);
        if (tok.Length > 0) parts.Add(tok);
        var cost = Autumn.Format.Cost(stage.CostUsd);
        if (cost.Length > 0) parts.Add(cost);
        if (stage.SourceTerr is { Length: > 0 } terr) parts.Add($"Terr: {terr}");
        return string.Join("  ·  ", parts);
    }

    private void OnPulseTick(object? sender, object e)
    {
        _pulsed = !_pulsed;
        foreach (var item in _activeItems)
            item.Opacity = _pulsed ? 0.45 : 1.0;
    }
}
