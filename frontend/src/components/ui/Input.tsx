"use client";

import { forwardRef } from "react";
import { cn } from "@/lib/utils";

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?:       string;
  error?:       string;
  hint?:        string;
  startIcon?:   React.ReactNode;
  endIcon?:     React.ReactNode;
  endAction?:   React.ReactNode;
}

const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, hint, startIcon, endIcon, endAction, className, id, ...props }, ref) => {
    const inputId = id ?? label?.replace(/\s/g, "-").toLowerCase();

    return (
      <div className="w-full space-y-1.5">
        {label && (
          <label htmlFor={inputId} className="form-label">
            {label}
            {props.required && <span className="text-danger-500 mr-0.5">*</span>}
          </label>
        )}

        <div className="relative">
          {/* Start icon */}
          {startIcon && (
            <span className="absolute inset-y-0 right-3 flex items-center pointer-events-none text-neutral-400">
              {startIcon}
            </span>
          )}

          <input
            ref={ref}
            id={inputId}
            className={cn(
              "form-input",
              startIcon && "pr-10",
              (endIcon || endAction) && "pl-10",
              error && "border-danger-500 focus:ring-danger-500 focus:border-danger-500",
              className
            )}
            {...props}
          />

          {/* End icon / action */}
          {(endIcon || endAction) && (
            <span className="absolute inset-y-0 left-3 flex items-center text-neutral-400">
              {endAction ?? endIcon}
            </span>
          )}
        </div>

        {error && (
          <p className="text-xs text-danger-600 flex items-center gap-1">
            <svg className="w-3.5 h-3.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
            </svg>
            {error}
          </p>
        )}
        {hint && !error && (
          <p className="text-xs text-neutral-500">{hint}</p>
        )}
      </div>
    );
  }
);
Input.displayName = "Input";

export { Input };

// Textarea variant
interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  error?: string;
  hint?:  string;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ label, error, hint, className, id, ...props }, ref) => {
    const areaId = id ?? label?.replace(/\s/g, "-").toLowerCase();
    return (
      <div className="w-full space-y-1.5">
        {label && (
          <label htmlFor={areaId} className="form-label">
            {label}
            {props.required && <span className="text-danger-500 mr-0.5">*</span>}
          </label>
        )}
        <textarea
          ref={ref}
          id={areaId}
          className={cn(
            "form-input min-h-[100px] resize-y",
            error && "border-danger-500 focus:ring-danger-500",
            className
          )}
          {...props}
        />
        {error && <p className="text-xs text-danger-600">{error}</p>}
        {hint && !error && <p className="text-xs text-neutral-500">{hint}</p>}
      </div>
    );
  }
);
Textarea.displayName = "Textarea";
