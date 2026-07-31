/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { set } from "lodash-es";
import { action, computed, makeObservable, observable, runInAction } from "mobx";
import type { TComplianceCategory, TComplianceRunSummary, TComplianceTemplate } from "@plane/types";
// services
import { ComplianceService } from "@/services/compliance.service";
// store
import type { CoreRootStore } from "./root.store";

export interface IComplianceStore {
  // observables
  categoryMap: Record<string, TComplianceCategory>;
  templateMap: Record<string, TComplianceTemplate>;
  fetchedWorkspaces: Record<string, boolean>;
  // computed
  categories: TComplianceCategory[];
  templates: TComplianceTemplate[];
  // fetch actions
  fetchCategoriesAndTemplates: (workspaceSlug: string) => Promise<void>;
  // crud actions
  createCategory: (workspaceSlug: string, name: string) => Promise<TComplianceCategory>;
  createTemplate: (workspaceSlug: string, data: Partial<TComplianceTemplate>) => Promise<TComplianceTemplate>;
  updateTemplate: (
    workspaceSlug: string,
    templateId: string,
    data: Partial<TComplianceTemplate>
  ) => Promise<TComplianceTemplate>;
  deleteTemplate: (workspaceSlug: string, templateId: string) => Promise<void>;
  toggleApplicability: (
    workspaceSlug: string,
    templateId: string,
    projectId: string,
    applicable: boolean
  ) => Promise<void>;
  triggerGenerate: (workspaceSlug: string, asOf?: string) => Promise<TComplianceRunSummary>;
}

export class ComplianceStore implements IComplianceStore {
  // root store
  rootStore;
  // observables
  categoryMap: Record<string, TComplianceCategory> = {};
  templateMap: Record<string, TComplianceTemplate> = {};
  fetchedWorkspaces: Record<string, boolean> = {};
  // services
  complianceService;

  constructor(_rootStore: CoreRootStore) {
    makeObservable(this, {
      categoryMap: observable,
      templateMap: observable,
      fetchedWorkspaces: observable,
      categories: computed,
      templates: computed,
      fetchCategoriesAndTemplates: action,
      createCategory: action,
      createTemplate: action,
      updateTemplate: action,
      deleteTemplate: action,
      toggleApplicability: action,
      triggerGenerate: action,
    });

    this.rootStore = _rootStore;
    this.complianceService = new ComplianceService();
  }

  get categories() {
    // eslint-disable-next-line unicorn/no-array-sort -- `Object.values()` above always returns a fresh array, so sorting it in place is safe (no shared/mutated state); `toSorted()` isn't available in this project's configured TS lib target
    return Object.values(this.categoryMap).sort((a, b) => a.name.localeCompare(b.name));
  }

  get templates() {
    // eslint-disable-next-line unicorn/no-array-sort -- `Object.values()` above always returns a fresh array, so sorting it in place is safe (no shared/mutated state); `toSorted()` isn't available in this project's configured TS lib target
    return Object.values(this.templateMap).sort((a, b) => a.title.localeCompare(b.title));
  }

  fetchCategoriesAndTemplates = async (workspaceSlug: string) => {
    const [categories, templates] = await Promise.all([
      this.complianceService.getCategories(workspaceSlug),
      this.complianceService.getTemplates(workspaceSlug),
    ]);
    runInAction(() => {
      categories.forEach((category) => set(this.categoryMap, [category.id], category));
      templates.forEach((template) => set(this.templateMap, [template.id], template));
      set(this.fetchedWorkspaces, workspaceSlug, true);
    });
  };

  createCategory = async (workspaceSlug: string, name: string) => {
    const category = await this.complianceService.createCategory(workspaceSlug, { name });
    runInAction(() => set(this.categoryMap, [category.id], category));
    return category;
  };

  createTemplate = async (workspaceSlug: string, data: Partial<TComplianceTemplate>) => {
    const template = await this.complianceService.createTemplate(workspaceSlug, data);
    runInAction(() => set(this.templateMap, [template.id], template));
    return template;
  };

  updateTemplate = async (workspaceSlug: string, templateId: string, data: Partial<TComplianceTemplate>) => {
    const original = this.templateMap[templateId];
    runInAction(() => set(this.templateMap, [templateId], { ...original, ...data }));
    try {
      const template = await this.complianceService.updateTemplate(workspaceSlug, templateId, data);
      runInAction(() => set(this.templateMap, [templateId], template));
      return template;
    } catch (error) {
      runInAction(() => set(this.templateMap, [templateId], original));
      throw error;
    }
  };

  deleteTemplate = async (workspaceSlug: string, templateId: string) => {
    const original = this.templateMap[templateId];
    runInAction(() => delete this.templateMap[templateId]);
    try {
      await this.complianceService.deleteTemplate(workspaceSlug, templateId);
    } catch (error) {
      runInAction(() => set(this.templateMap, [templateId], original));
      throw error;
    }
  };

  toggleApplicability = async (workspaceSlug: string, templateId: string, projectId: string, applicable: boolean) => {
    const original = this.templateMap[templateId];
    if (!original) return;

    const nextProjectIds = applicable
      ? Array.from(new Set([...original.applicable_project_ids, projectId]))
      : original.applicable_project_ids.filter((id) => id !== projectId);

    runInAction(() => set(this.templateMap, [templateId, "applicable_project_ids"], nextProjectIds));
    try {
      await this.complianceService.toggleApplicability(workspaceSlug, templateId, projectId, applicable);
    } catch (error) {
      runInAction(() => set(this.templateMap, [templateId, "applicable_project_ids"], original.applicable_project_ids));
      throw error;
    }
  };

  triggerGenerate = async (workspaceSlug: string, asOf?: string) =>
    this.complianceService.triggerGenerate(workspaceSlug, asOf);
}
